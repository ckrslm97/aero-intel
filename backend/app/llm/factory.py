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

    async def sentiment(self, title: str, content: str) -> str:
        return await self._call("sentiment", title, content)

    async def extract_entities(self, title: str, content: str) -> list[EntityMention]:
        return await self._call("extract_entities", title, content)


def get_llm_provider() -> LLMProvider:
    settings = get_settings()

    if settings.llm_provider == "ollama":
        base_url = settings.llm_base_url or "http://localhost:11434"
        return FallbackProvider(OllamaProvider(base_url, settings.llm_model))

    if settings.llm_provider == "openai_compat":
        if not settings.llm_base_url:
            logger.warning("openai_compat_missing_base_url_using_heuristic")
            return HeuristicProvider()
        return FallbackProvider(
            OpenAICompatProvider(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
        )

    return HeuristicProvider()
