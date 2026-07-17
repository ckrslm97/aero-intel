"""Every enrichment task the pipeline needs, behind one interface -- so the
pipeline never knows whether it's talking to Ollama, an OpenAI-compatible API,
or the built-in no-key heuristic fallback.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class EntityMention:
    entity_type: str  # airline | airport | country
    name: str
    code: str | None


class LLMProvider(Protocol):
    name: str

    async def generate_headline(self, title: str, content: str) -> str: ...
    async def generate_summary(self, title: str, content: str) -> str: ...
    async def categorize(self, title: str, content: str) -> str: ...
    async def subcategorize(self, title: str, content: str, category: str) -> str | None: ...
    async def sentiment(self, title: str, content: str) -> str: ...
    async def extract_entities(self, title: str, content: str) -> list[EntityMention]: ...
    async def translate(self, text: str, target: str = "tr") -> str | None:
        """Translate `text` into `target`. Returns None when this provider has
        no real translation capability (the heuristic fallback) -- callers must
        treat None as "leave untranslated", never as an empty translation."""
        ...
