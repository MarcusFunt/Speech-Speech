from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class STTError(RuntimeError):
    """Base class for transcription failures that can be shown to clients."""


class STTUnavailableError(STTError):
    """Raised when the configured transcription backend is not installed or reachable."""


class TranscriptionFailedError(STTError):
    """Raised when a configured transcription backend fails while processing audio."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None = None
    duration_s: float | None = None
    backend: str = "unknown"


class STTAdapter(ABC):
    name: str

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, filename: str = "input.webm") -> TranscriptionResult:
        raise NotImplementedError
