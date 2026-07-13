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
    async def sentiment(self, title: str, content: str) -> str: ...
    async def extract_entities(self, title: str, content: str) -> list[EntityMention]: ...
