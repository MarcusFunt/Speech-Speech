from __future__ import annotations

import asyncio
import importlib.util
import io
from pathlib import Path

from local_assistant.config import TTSEngineConfig
from local_assistant.tts.base import AudioResult, TTSAdapter, TTSFeatures


class ChatterboxTTSAdapter(TTSAdapter):
    name = "chatterbox"
    features = TTSFeatures(
        supports_streaming=False,
        supports_emotion=True,
        supports_nonverbals=True,
        supports_voice_cloning=True,
        estimated_latency="medium",
    )

    def __init__(self, config: TTSEngineConfig):
        self.config = config
        self._model = None
        self._sample_rate = 24000
        self._load_error: str | None = None

    def is_available(self) -> bool:
        return (
            self.config.enabled
            and importlib.util.find_spec("chatterbox") is not None
            and importlib.util.find_spec("torchaudio") is not None
        )

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "available": self.is_available(),
            "model": self.config.model,
            "device": self.config.device,
            "load_error": self._load_error,
            "needs": ["chatterbox-tts", "torch", "torchaudio"],
        }

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            try:
                from chatterbox.tts_turbo import ChatterboxTurboTTS

                self._model = ChatterboxTurboTTS.from_pretrained(device=self.config.device)
            except Exception:
                from chatterbox.tts import ChatterboxTTS

                self._model = ChatterboxTTS.from_pretrained(device=self.config.device)
            self._sample_rate = int(getattr(self._model, "sr", 24000))
        except Exception as exc:
            self._load_error = str(exc)
            raise
        return self._model

    async def generate(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> AudioResult:
        if not self.is_available():
            raise RuntimeError("Chatterbox is not installed or not enabled")
        return await asyncio.to_thread(self._generate_sync, text, voice)

    def _generate_sync(self, text: str, voice: str | None) -> AudioResult:
        import torchaudio as ta

        model = self._get_model()
        kwargs = {}
        if voice and Path(voice).exists():
            kwargs["audio_prompt_path"] = voice
        wav = model.generate(text, **kwargs)
        buffer = io.BytesIO()
        ta.save(buffer, wav.cpu(), self._sample_rate, format="wav")
        return AudioResult(
            audio=buffer.getvalue(),
            media_type="audio/wav",
            sample_rate=self._sample_rate,
            engine=self.name,
            voice=voice,
        )
