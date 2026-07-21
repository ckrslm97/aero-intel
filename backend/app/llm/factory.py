from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.base import EntityMention, LLMProvider
from app.llm.heuristic import HeuristicProvider
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatProvider

logger = get_logger(__name__)


class FallbackProvider:
    """Wraps a live provider so any failure -- network error, timeout, or
    unparseable output -- transparently falls back to the heuristic pipeline
    for that single call instead of losing the article.
    """

    def __init__(self, primary: LLMProvider):
        self.primary = primary
        self.fallback = HeuristicProvider()
        self.name = primary.name

    async def _call(self, method: str, title: str, content: str):
        try:
            return await getattr(self.primary, method)(title, content)
        except Exception as exc:  # noqa: BLE001 -- any provider failure must not crash enrichment
            logger.warning(
                "llm_call_failed_falling_back",
                provider=self.primary.name,
                method=method,
                error=str(exc),
            )
            return await getattr(self.fallback, method)(title, content)

    async def generate_headline(self, title: str, content: str) -> str:
        return await self._call("generate_headline", title, content)

    async def generate_summary(self, title: str, content: str) -> str:
        return await self._call("generate_summary", title, content)

    async def categorize(self, title: str, content: str) -> str:
        return await self._call("categorize", title, content)

    async def subcategorize(self, title: str, content: str, category: str) -> str | None:
        try:
            return await self.primary.subcategorize(title, content, category)
        except Exception as exc:  # noqa: BLE001 -- any provider failure must not crash enrichment
            logger.warning(
                "llm_call_failed_falling_back",
                provider=self.primary.name,
                method="subcategorize",
                error=str(exc),
            )
            return await self.fallback.subcategorize(title, content, category)

    async def translate(self, text: str, target: str = "tr") -> str | None:
        try:
            return await self.primary.translate(text, target)
        except Exception as exc:  # noqa: BLE001 -- translation failure must not crash enrichment
            logger.warning(
                "llm_call_failed_falling_back", provider=self.primary.name, method="translate", error=str(exc)
            )
            # Fall back to "not translated" (None) rather than the heuristic's
            # own translate(), which is also always None -- same outcome either way.
            return None

    async def translate_pair(
        self, headline: str, summary: str, target: str = "tr"
    ) -> tuple[str | None, str | None]:
        """Forward the single-call path when the wrapped provider has one.

        Without this the wrapper silently hid the capability -- BudgetedProvider
        asked FallbackProvider for translate_pair, didn't find it, and fell back
        to two calls, so the halving never actually reached production.
        """
        pair = getattr(self.primary, "translate_pair", None)
        if pair is None:
            return (
                await self.translate(headline, target),
                await self.translate(summary, target) if summary else None,
            )
        try:
            return await pair(headline, summary, target)
        except Exception as exc:  # noqa: BLE001 -- translation failure must not crash enrichment
            logger.warning(
                "llm_call_failed_falling_back",
                provider=self.primary.name,
                method="translate_pair",
                error=str(exc),
            )
            return None, None

    async def sentiment(self, title: str, content: str) -> str:
        return await self._call("sentiment", title, content)

    async def extract_entities(self, title: str, content: str) -> list[EntityMention]:
        return await self._call("extract_entities", title, content)


class BudgetedProvider:
    """Spends the LLM only on the tasks it's genuinely needed for.

    The binding constraint is the free tier: Groq allows llama-3.3-70b just
    1,000 requests and 100k tokens per *day*. Even a translation-only live path
    costs 4 LLM calls per article (categorize, subcategorize, translate x2), and
    the two classification calls each ship the article body -- so tokens, not
    requests, run out first (~2k tokens/article -> ~50 articles/day on the 70b).

    So the budget goes where the heuristic genuinely can't compete:
      * translate -- the heuristic cannot translate at all; quality matters, so
        this stays on the strong `live` model;
      * categorize/subcategorize -- keyword matching is the weakest link, and
        correct categories are what the newspaper's whole navigation rests on.
        These are routed to the cheaper high-throughput `fast` model (e.g. Groq
        llama-3.1-8b-instant, 500k tokens/day) when one is configured, which
        roughly triples daily capacity to ~140 articles. Without a fast model,
        `fast` is just `live`.
    Summary, sentiment and entities stay on the local heuristic: they're decent,
    instant, and free. LLM_FULL_PIPELINE=true opts everything back in.
    """

    def __init__(self, live: LLMProvider, fast: LLMProvider | None = None):
        self.live = live
        self.fast = fast or live
        self.local = HeuristicProvider()
        self.name = live.name

    async def generate_headline(self, title: str, content: str) -> str:
        return await self.local.generate_headline(title, content)

    async def generate_summary(self, title: str, content: str) -> str:
        return await self.local.generate_summary(title, content)

    async def sentiment(self, title: str, content: str) -> str:
        return await self.local.sentiment(title, content)

    async def extract_entities(self, title: str, content: str) -> list[EntityMention]:
        return await self.local.extract_entities(title, content)

    async def categorize(self, title: str, content: str) -> str:
        return await self.fast.categorize(title, content)

    async def subcategorize(self, title: str, content: str, category: str) -> str | None:
        return await self.fast.subcategorize(title, content, category)

    async def translate(self, text: str, target: str = "tr") -> str | None:
        return await self.live.translate(text, target)

    async def translate_pair(
        self, headline: str, summary: str, target: str = "tr"
    ) -> tuple[str | None, str | None]:
        pair = getattr(self.live, "translate_pair", None)
        if pair is not None:
            return await pair(headline, summary, target)
        return (
            await self.live.translate(headline, target),
            await self.live.translate(summary, target) if summary else None,
        )


def get_llm_provider() -> LLMProvider:
    settings = get_settings()

    live: LLMProvider | None = None
    fast: LLMProvider | None = None
    if settings.llm_provider == "ollama":
        base_url = settings.llm_base_url or "http://localhost:11434"
        live = FallbackProvider(OllamaProvider(base_url, settings.llm_model))
    elif settings.llm_provider == "openai_compat":
        if not settings.llm_base_url:
            logger.warning("openai_compat_missing_base_url_using_heuristic")
            return HeuristicProvider()
        live = FallbackProvider(
            OpenAICompatProvider(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
        )
        # A separate, cheaper model for the token-heavy classification calls.
        # Same base_url + key, different model id -- see BudgetedProvider.
        if settings.llm_model_fast and settings.llm_model_fast != settings.llm_model:
            fast = FallbackProvider(
                OpenAICompatProvider(
                    settings.llm_base_url, settings.llm_model_fast, settings.llm_api_key
                )
            )

    if live is None:
        return HeuristicProvider()
    return live if settings.llm_full_pipeline else BudgetedProvider(live, fast)
