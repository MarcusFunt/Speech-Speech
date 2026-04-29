from __future__ import annotations

from local_assistant.stt.base import STTAdapter, TranscriptionResult


class MockSTTAdapter(STTAdapter):
    name = "mock"
    default_transcript = "This is a configured mock transcription."

    def __init__(self, transcript: str | None = None, language: str | None = "en"):
        self.transcript = (transcript or "").strip() or self.default_transcript
        self.language = language

    def is_available(self) -> bool:
        return True

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "available": True,
            "mode": "debug",
            "transcript_preview": self.transcript[:80],
        }

    async def transcribe(self, audio_bytes: bytes, filename: str = "input.webm") -> TranscriptionResult:
        return TranscriptionResult(
            text=self.transcript,
            language=self.language,
            backend=self.name,
        )
