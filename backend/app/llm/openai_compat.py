"""Any OpenAI-wire-compatible chat completions API: OpenAI itself, or a gateway
that speaks the same wire format (Ollama's own /v1 endpoint, OpenRouter,
Together, Groq, etc). For Anthropic models specifically, point base_url at such
a gateway -- Anthropic's native API uses a different request/response shape.
"""
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
    summary_prompt,
)

REQUEST_TIMEOUT = httpx.Timeout(60.0)


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url: str, model: str, api_key: str | None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

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
