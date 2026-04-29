from __future__ import annotations

import asyncio
from typing import AsyncIterator

from local_assistant.llm.base import LLMAdapter


MOCK_FALLBACK_PREFIX = "Okay, I am running in local debug mode right now."


def is_mock_fallback_text(text: str) -> bool:
    return text.strip().startswith(MOCK_FALLBACK_PREFIX)


class MockLLMAdapter(LLMAdapter):
    name = "mock"

    async def health_check(self) -> dict:
        return {"name": self.name, "available": True, "mode": "debug"}

    async def stream_chat(self, messages: list[dict[str, str]], cancel_event) -> AsyncIterator[str]:
        user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        reply = (
            f"{MOCK_FALLBACK_PREFIX} "
            "I heard you say: "
            f"{user_text[:120] or 'something short'}. "
            "Once Ollama is reachable, I will use the selected local model instead."
        )
        for token in reply.split(" "):
            if cancel_event.is_set():
                return
            yield token + " "
            await asyncio.sleep(0.025)
