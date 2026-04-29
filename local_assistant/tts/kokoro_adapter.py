from __future__ import annotations

import asyncio
import importlib.util
import io
from typing import Any

from local_assistant.config import TTSEngineConfig
from local_assistant.tts.base import AudioResult, TTSAdapter, TTSFeatures


class KokoroTTSAdapter(TTSAdapter):
    name = "kokoro"
    features = TTSFeatures(
        supports_streaming=False,
        supports_emotion=False,
        supports_nonverbals=False,
        supports_voice_cloning=False,
        estimated_latency="low",
    )

    def __init__(self, config: TTSEngineConfig):
        self.config = config
        self._pipeline = None
        self._load_error: str | None = None
        self._stopped = False

    def is_available(self) -> bool:
        return (
            self.config.enabled
            and importlib.util.find_spec("kokoro") is not None
            and importlib.util.find_spec("soundfile") is not None
        )

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "available": self.is_available(),
            "model": self.config.model,
            "device": self.config.device,
            "default_voice": self.config.default_voice,
            "load_error": self._load_error,
            "needs": ["kokoro>=0.9.4", "soundfile", "espeak-ng"],
        }

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        from kokoro import KPipeline

        lang_code = str(self.config.extra.get("lang_code", "a"))
        try:
            self._pipeline = KPipeline(lang_code=lang_code)
        except Exception as exc:
            self._load_error = str(exc)
            raise
        return self._pipeline

    async def generate(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> AudioResult:
        if not self.is_available():
            raise RuntimeError("Kokoro is not installed or not enabled")
        self._stopped = False
        return await asyncio.to_thread(self._generate_sync, text, voice, speed)

    def _generate_sync(self, text: str, voice: str | None, speed: float) -> AudioResult:
        import numpy as np
        import soundfile as sf

        pipeline = self._get_pipeline()
        selected_voice = voice or self.config.default_voice or "af_heart"
        generator = pipeline(text, voice=selected_voice, speed=speed, split_pattern=r"\n+")
        arrays: list[Any] = []
        for _, _, audio in generator:
            if self._stopped:
                break
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            arrays.append(audio)
        if not arrays:
            raise RuntimeError("Kokoro generated no audio")
        merged = np.concatenate(arrays)
        buffer = io.BytesIO()
        sf.write(buffer, merged, 24000, format="WAV")
        return AudioResult(
            audio=buffer.getvalue(),
            media_type="audio/wav",
            sample_rate=24000,
            engine=self.name,
            voice=selected_voice,
        )

    def stop(self) -> None:
        self._stopped = True
