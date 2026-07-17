"""Local Ollama provider -- talks to Ollama's native /api/generate endpoint."""
import json

import httpx

from app.llm.base import EntityMention
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

REQUEST_TIMEOUT = httpx.Timeout(60.0)


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def _generate(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
            return response.json()["response"].strip()

    async def generate_headline(self, title: str, content: str) -> str:
        return await self._generate(headline_prompt(title, content))

    async def generate_summary(self, title: str, content: str) -> str:
        return await self._generate(summary_prompt(title, content))

    async def categorize(self, title: str, content: str) -> str:
        result = (await self._generate(categorize_prompt(title, content))).strip().lower()
        if result not in VALID_CATEGORIES:
            raise ValueError(f"Ollama returned an unrecognized category: {result!r}")
        return result

    async def subcategorize(self, title: str, content: str, category: str) -> str | None:
        sub_options = SUBCATEGORY_KEYWORDS.get(category)
        if not sub_options or category == "events":
            return None
        result = (await self._generate(subcategorize_prompt(title, content, category))).strip().lower()
        return result if result in sub_options else None

    async def translate(self, text: str, target: str = "tr") -> str | None:
        return await self._generate(translate_prompt(text, target))

    async def sentiment(self, title: str, content: str) -> str:
        result = (await self._generate(sentiment_prompt(title, content))).strip().lower()
        if result not in VALID_SENTIMENTS:
            raise ValueError(f"Ollama returned an unrecognized sentiment: {result!r}")
        return result

    async def extract_entities(self, title: str, content: str) -> list[EntityMention]:
        raw = await self._generate(entities_prompt(title, content))
        data = json.loads(raw)  # raises ValueError/JSONDecodeError on malformed output
        return [
            EntityMention(item["entity_type"], item["name"], item.get("code"))
            for item in data
        ]
