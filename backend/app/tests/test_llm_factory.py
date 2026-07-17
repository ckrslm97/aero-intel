"""Which tasks are allowed to spend LLM budget is a deliberate decision, not an
accident of wiring -- a free Groq tier only affords ~1k requests / 100k tokens a
day, and the site enriches hundreds of articles. These pin that routing.
"""
import pytest

from app.core.config import get_settings
from app.llm.base import EntityMention
from app.llm.factory import BudgetedProvider, get_llm_provider
from app.llm.heuristic import HeuristicProvider


class _SpyLive:
    """Stands in for a live LLM; records which tasks were routed to it."""

    name = "spy"

    def __init__(self):
        self.calls: list[str] = []

    async def generate_headline(self, title, content):
        self.calls.append("generate_headline")
        return "llm headline"

    async def generate_summary(self, title, content):
        self.calls.append("generate_summary")
        return "llm summary"

    async def sentiment(self, title, content):
        self.calls.append("sentiment")
        return "positive"

    async def extract_entities(self, title, content):
        self.calls.append("extract_entities")
        return [EntityMention("airline", "Spy Air", "SP")]

    async def categorize(self, title, content):
        self.calls.append("categorize")
        return "revenue_management"

    async def subcategorize(self, title, content, category):
        self.calls.append("subcategorize")
        return "pricing"

    async def translate(self, text, target="tr"):
        self.calls.append("translate")
        return "çeviri"


@pytest.fixture
def spy_budgeted():
    spy = _SpyLive()
    return spy, BudgetedProvider(spy)


async def test_translation_and_categorisation_go_to_the_llm(spy_budgeted):
    spy, provider = spy_budgeted

    assert await provider.translate("Hello") == "çeviri"
    assert await provider.categorize("t", "c") == "revenue_management"
    assert await provider.subcategorize("t", "c", "revenue_management") == "pricing"

    assert spy.calls == ["translate", "categorize", "subcategorize"]


async def test_cheap_tasks_stay_on_the_local_heuristic(spy_budgeted):
    spy, provider = spy_budgeted

    # The heuristic does these well enough for free; spending daily LLM budget
    # on them would starve translation.
    assert await provider.generate_headline("Real title", "body") == "Real title"
    await provider.generate_summary("t", "One sentence. Two sentence.")
    await provider.sentiment("Airline celebrates record growth", "milestone")
    await provider.extract_entities("Turkish Airlines to Egypt", "Turkish Airlines and Egypt")

    assert spy.calls == []


async def test_heuristic_when_no_provider_configured(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    assert isinstance(get_llm_provider(), HeuristicProvider)
    get_settings.cache_clear()


async def test_full_pipeline_flag_opts_everything_back_into_the_llm(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("LLM_FULL_PIPELINE", "true")

    provider = get_llm_provider()
    assert not isinstance(provider, BudgetedProvider)

    get_settings.cache_clear()


async def test_budgeted_by_default_when_a_live_provider_is_configured(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.delenv("LLM_FULL_PIPELINE", raising=False)

    assert isinstance(get_llm_provider(), BudgetedProvider)

    get_settings.cache_clear()


async def test_classification_routes_to_the_fast_model_translation_to_the_strong_one():
    live, fast = _SpyLive(), _SpyLive()
    provider = BudgetedProvider(live, fast)

    await provider.categorize("t", "c")
    await provider.subcategorize("t", "c", "revenue_management")
    await provider.translate("Hello")

    # Token-heavy classification goes to the cheap high-throughput model...
    assert fast.calls == ["categorize", "subcategorize"]
    # ...while quality-critical translation stays on the strong model.
    assert live.calls == ["translate"]


async def test_without_a_fast_model_everything_live_uses_the_single_model():
    live = _SpyLive()
    provider = BudgetedProvider(live)  # no fast

    await provider.categorize("t", "c")
    await provider.translate("Hello")

    assert live.calls == ["categorize", "translate"]


async def test_fast_model_setting_builds_a_second_provider(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setenv("LLM_MODEL_FAST", "llama-3.1-8b-instant")
    monkeypatch.delenv("LLM_FULL_PIPELINE", raising=False)

    provider = get_llm_provider()
    assert isinstance(provider, BudgetedProvider)
    # FallbackProvider -> OpenAICompatProvider; the two paths carry the two models.
    assert provider.live.primary.model == "llama-3.3-70b-versatile"
    assert provider.fast.primary.model == "llama-3.1-8b-instant"
    assert provider.fast is not provider.live

    get_settings.cache_clear()


async def test_no_fast_model_means_fast_is_live(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.delenv("LLM_MODEL_FAST", raising=False)
    monkeypatch.delenv("LLM_FULL_PIPELINE", raising=False)

    provider = get_llm_provider()
    assert isinstance(provider, BudgetedProvider)
    assert provider.fast is provider.live

    get_settings.cache_clear()
