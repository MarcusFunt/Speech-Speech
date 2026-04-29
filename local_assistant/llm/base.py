from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMAdapter(ABC):
    name: str

    @abstractmethod
    async def health_check(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(self, messages: list[dict[str, str]], cancel_event) -> AsyncIterator[str]:
        raise NotImplementedError
