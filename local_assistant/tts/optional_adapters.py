from __future__ import annotations

import importlib.util

import httpx

from local_assistant.config import TTSEngineConfig
from local_assistant.tts.base import AudioResult, TTSAdapter, TTSFeatures


class EndpointOrPackageTTSAdapter(TTSAdapter):
    package_name: str | None = None

    def __init__(self, name: str, config: TTSEngineConfig, features: TTSFeatures):
        self.name = name
        self.config = config
        self.features = features
        self._last_error: str | None = None

    def is_available(self) -> bool:
        if not self.config.enabled:
            return False
        if self.config.endpoint_url:
            return True
        return False

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "available": self.is_available(),
            "endpoint_url": self.config.endpoint_url,
            "package_name": self.package_name,
            "package_detected": bool(self.package_name and importlib.util.find_spec(self.package_name)),
            "last_error": self._last_error,
            "mode": "external_endpoint" if self.config.endpoint_url else "package_stub",
        }

    async def generate(self, text: str, voice: str | None = None, style: str | None = None, speed: float = 1.0) -> AudioResult:
        if not self.config.endpoint_url:
            raise RuntimeError(f"{self.name} package support is not implemented yet; configure endpoint_url to use a local server")
        payload = {"text": text, "voice": voice, "style": style, "speed": speed}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(self.config.endpoint_url, json=payload)
            response.raise_for_status()
            media_type = response.headers.get("content-type", "audio/wav").split(";")[0]
            return AudioResult(
                audio=response.content,
                media_type=media_type,
                sample_rate=24000,
                engine=self.name,
                voice=voice,
            )
        except Exception as exc:
            self._last_error = str(exc)
            raise


class DiaTTSAdapter(EndpointOrPackageTTSAdapter):
    package_name = "dia"

    def __init__(self, config: TTSEngineConfig):
        super().__init__(
            "dia",
            config,
            TTSFeatures(
                supports_streaming=False,
                supports_emotion=True,
                supports_nonverbals=True,
                supports_voice_cloning=False,
                estimated_latency="experimental",
            ),
        )


class OrpheusTTSAdapter(EndpointOrPackageTTSAdapter):
    package_name = "orpheus_tts"

    def __init__(self, config: TTSEngineConfig):
        super().__init__(
            "orpheus",
            config,
            TTSFeatures(
                supports_streaming=True,
                supports_emotion=True,
                supports_nonverbals=True,
                supports_voice_cloning=False,
                estimated_latency="experimental",
            ),
        )
