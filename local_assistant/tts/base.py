from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class TTSFeatures:
    supports_streaming: bool = False
    supports_emotion: bool = False
    supports_nonverbals: bool = False
    supports_voice_cloning: bool = False
    estimated_latency: str = "unknown"


@dataclass(frozen=True)
class AudioResult:
    audio: bytes
    media_type: str = "audio/wav"
    sample_rate: int = 24000
    engine: str = "unknown"
    voice: str | None = None


class TTSAdapter(ABC):
    name: str
    features: TTSFeatures

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def generate(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> AudioResult:
        raise NotImplementedError

    async def stream(
        self, text_chunks, voice: str | None = None, style: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[AudioResult]:
        for chunk in text_chunks:
            yield await self.generate(chunk, voice=voice, style=style, speed=speed)

    def stop(self) -> None:
        return None
