from __future__ import annotations

from typing import AsyncIterator

from local_assistant.config import LLMConfig
from local_assistant.llm.base import LLMAdapter
from local_assistant.llm.mock import MockLLMAdapter
from local_assistant.llm.openai_compatible import OpenAICompatibleLLMAdapter


class LLMManager(LLMAdapter):
    name = "llm_manager"

    def __init__(self, config: LLMConfig):
        self.config = config
        self.primary: LLMAdapter
        if config.provider in {"ollama", "openai_compatible"}:
            self.primary = OpenAICompatibleLLMAdapter(config)
        else:
            self.primary = MockLLMAdapter()
        self.fallback = MockLLMAdapter()
        self.last_error: str | None = None
        self.used_fallback = False

    async def health_check(self) -> dict:
        primary = await self.primary.health_check()
        fallback = await self.fallback.health_check()
        return {
            "name": self.name,
            "provider": self.config.provider,
            "primary": primary,
            "fallback": fallback,
            "last_error": self.last_error,
        }

    async def stream_chat(self, messages: list[dict[str, str]], cancel_event) -> AsyncIterator[str]:
        self.used_fallback = False
        try:
            async for delta in self.primary.stream_chat(messages, cancel_event):
                yield delta
            self.last_error = None
            return
        except Exception as exc:
            self.last_error = str(exc)
            if cancel_event.is_set():
                return
        self.used_fallback = True
        async for delta in self.fallback.stream_chat(messages, cancel_event):
            yield delta
