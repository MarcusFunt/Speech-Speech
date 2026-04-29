from __future__ import annotations

from local_assistant.stt.base import STTAdapter, TranscriptionResult


class MockSTTAdapter(STTAdapter):
    name = "mock"

    def is_available(self) -> bool:
        return True

    def health_check(self) -> dict:
        return {"name": self.name, "available": True, "mode": "debug"}

    async def transcribe(self, audio_bytes: bytes, filename: str = "input.webm") -> TranscriptionResult:
        return TranscriptionResult(
            text="I heard your push-to-talk recording, but faster-whisper is not installed yet.",
            backend=self.name,
        )
