"""Any OpenAI-wire-compatible chat completions API: OpenAI itself, or a gateway
that speaks the same wire format (Ollama's own /v1 endpoint, OpenRouter,
Together, Groq, etc). For Anthropic models specifically, point base_url at such
a gateway -- Anthropic's native API uses a different request/response shape.
"""
import json

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
    translate_prompt,
)
from app.taxonomy import SUBCATEGORY_KEYWORDS

logger = get_logger(__name__)

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
            return response.json()["choices"][0]["message"]["content"].strip()

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
