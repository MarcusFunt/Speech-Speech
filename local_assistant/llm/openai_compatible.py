from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from local_assistant.config import LLMConfig
from local_assistant.llm.base import LLMAdapter


class OpenAICompatibleLLMAdapter(LLMAdapter):
    name = "openai_compatible"

    def __init__(self, config: LLMConfig):
        self.config = config

    async def health_check(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.config.base_url.rstrip('/')}/models")
            return {
                "name": self.name,
                "available": response.status_code < 500,
                "base_url": self.config.base_url,
                "model": self.config.model,
                "status_code": response.status_code,
            }
        except Exception as exc:
            return {
                "name": self.name,
                "available": False,
                "base_url": self.config.base_url,
                "model": self.config.model,
                "error": str(exc),
            }

    async def stream_chat(self, messages: list[dict[str, str]], cancel_event) -> AsyncIterator[str]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        timeout = httpx.Timeout(self.config.timeout_s, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        return
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
