"""Any OpenAI-wire-compatible chat completions API: OpenAI itself, or a gateway
that speaks the same wire format (Ollama's own /v1 endpoint, OpenRouter,
Together, Groq, etc). For Anthropic models specifically, point base_url at such
a gateway -- Anthropic's native API uses a different request/response shape.
"""
import json
import re

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger
from app.llm.base import EntityMention
from app.llm.sanitize import clean_translation
from app.llm.prompts import (
    VALID_CATEGORIES,
    VALID_SENTIMENTS,
    categorize_prompt,
    entities_prompt,
    headline_prompt,
    sentiment_prompt,
    subcategorize_prompt,
    summary_prompt,
    translate_pair_prompt,
    translate_prompt,
)
from app.taxonomy import SUBCATEGORY_KEYWORDS

logger = get_logger(__name__)

_HEADLINE_MARKER = re.compile(r"^\s*(?:HEADLINE|BAŞLIK|BASLIK)\s*:\s*", re.IGNORECASE)
_SUMMARY_MARKER = re.compile(r"^\s*(?:SUMMARY|ÖZET|OZET)\s*:\s*", re.IGNORECASE)


def _split_translation_pair(raw: str | None) -> tuple[str | None, str | None]:
    """Pull the two fields out of a HEADLINE:/SUMMARY: response.

    Returns (None, None) when the headline marker is missing, which is the
    caller's signal to retry as two separate calls rather than guess.
    """
    if not raw:
        return None, None

    headline_lines: list[str] = []
    summary_lines: list[str] = []
    target: list[str] | None = None
    for line in raw.splitlines():
        if _HEADLINE_MARKER.match(line):
            target = headline_lines
            line = _HEADLINE_MARKER.sub("", line, count=1)
        elif _SUMMARY_MARKER.match(line):
            target = summary_lines
            line = _SUMMARY_MARKER.sub("", line, count=1)
        if target is not None and line.strip():
            target.append(line.strip())

    headline = " ".join(headline_lines).strip() or None
    summary = " ".join(summary_lines).strip() or None
    return headline, summary


REQUEST_TIMEOUT = httpx.Timeout(60.0)


def _is_retryable(exc: BaseException) -> bool:
    """429 and 5xx are worth waiting out; a 400/401 never is.

    Free tiers rate-limit by the minute (Groq: 30 req/min), so a bulk
    enrichment run *will* hit 429 -- backing off is normal operation here, not
    an error path.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url: str, model: str, api_key: str | None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _generate(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=headers) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
            )
            if response.status_code == 429:
                logger.info("llm_rate_limited_backing_off", retry_after=response.headers.get("retry-after"))
            response.raise_for_status()
            payload = response.json()
            # The daily budget was, until now, arithmetic in a comment. Groq
            # reports what is actually left on every response; logging it makes
            # the ceiling visible in the job output instead of a guess.
            usage = payload.get("usage") or {}
            logger.info(
                "llm_call_complete",
                model=self.model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                tokens_remaining_day=response.headers.get("x-ratelimit-remaining-tokens"),
                requests_remaining_day=response.headers.get("x-ratelimit-remaining-requests"),
            )
            return payload["choices"][0]["message"]["content"].strip()

    async def generate_headline(self, title: str, content: str) -> str:
        return await self._generate(headline_prompt(title, content))

    async def generate_summary(self, title: str, content: str) -> str:
        return await self._generate(summary_prompt(title, content))

    async def categorize(self, title: str, content: str) -> str:
        result = (await self._generate(categorize_prompt(title, content))).strip().lower()
        if result not in VALID_CATEGORIES:
            raise ValueError(f"Provider returned an unrecognized category: {result!r}")
        return result

    async def subcategorize(self, title: str, content: str, category: str) -> str | None:
        sub_options = SUBCATEGORY_KEYWORDS.get(category)
        if not sub_options or category == "events":
            return None
        result = (await self._generate(subcategorize_prompt(title, content, category))).strip().lower()
        return result if result in sub_options else None

    async def translate(self, text: str, target: str = "tr") -> str | None:
        # Small models sometimes append invented prose or translator commentary
        # after the actual translation; clean_translation keeps only what can be
        # trusted, or None so the article stays honestly untranslated.
        raw = await self._generate(translate_prompt(text, target))
        return clean_translation(text, raw)

    async def translate_pair(
        self, headline: str, summary: str, target: str = "tr"
    ) -> tuple[str | None, str | None]:
        """Translate headline and summary in ONE call.

        Falls back to the two-call path when the model ignores the response
        format -- a mangled answer must never silently truncate an article, and
        the per-field sanitizer stays the last line of defence either way.
        """
        if not summary:
            return await self.translate(headline, target), None

        raw = await self._generate(translate_pair_prompt(headline, summary, target))
        parsed_headline, parsed_summary = _split_translation_pair(raw)
        if parsed_headline is None:
            logger.warning("translate_pair_unparsable_falling_back")
            return (
                await self.translate(headline, target),
                await self.translate(summary, target),
            )
        return (
            clean_translation(headline, parsed_headline),
            clean_translation(summary, parsed_summary) if parsed_summary else None,
        )

    async def sentiment(self, title: str, content: str) -> str:
        result = (await self._generate(sentiment_prompt(title, content))).strip().lower()
        if result not in VALID_SENTIMENTS:
            raise ValueError(f"Provider returned an unrecognized sentiment: {result!r}")
        return result

    async def extract_entities(self, title: str, content: str) -> list[EntityMention]:
        raw = await self._generate(entities_prompt(title, content))
        data = json.loads(raw)
        return [
            EntityMention(item["entity_type"], item["name"], item.get("code"))
            for item in data
        ]
