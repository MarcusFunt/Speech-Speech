from __future__ import annotations

import asyncio

from local_assistant.audio.wav import synthetic_voice_wav
from local_assistant.tts.base import AudioResult, TTSAdapter, TTSFeatures


class MockTTSAdapter(TTSAdapter):
    name = "mock"
    features = TTSFeatures(
        supports_streaming=True,
        supports_emotion=False,
        supports_nonverbals=False,
        supports_voice_cloning=False,
        estimated_latency="very low",
    )

    def is_available(self) -> bool:
        return True

    def health_check(self) -> dict:
        return {"name": self.name, "available": True, "mode": "debug"}

    async def generate(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> AudioResult:
        await asyncio.sleep(0)
        return AudioResult(
            audio=synthetic_voice_wav(text),
            engine=self.name,
            voice=voice,
        )
