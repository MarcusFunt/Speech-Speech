from __future__ import annotations

import asyncio

from local_assistant.config import TTSConfig, TTSEngineConfig
from local_assistant.tts.base import AudioResult, TTSAdapter
from local_assistant.tts.chatterbox_adapter import ChatterboxTTSAdapter
from local_assistant.tts.kokoro_adapter import KokoroTTSAdapter
from local_assistant.tts.mock import MockTTSAdapter
from local_assistant.tts.optional_adapters import DiaTTSAdapter, OrpheusTTSAdapter


class TTSManager:
    def __init__(self, config: TTSConfig):
        self.config = config
        self.adapters: dict[str, TTSAdapter] = self._build_adapters(config.engines)
        self._lock = asyncio.Lock()

    def _build_adapters(self, engines: dict[str, TTSEngineConfig]) -> dict[str, TTSAdapter]:
        return {
            "kokoro": KokoroTTSAdapter(engines.get("kokoro", TTSEngineConfig())),
            "chatterbox": ChatterboxTTSAdapter(engines.get("chatterbox", TTSEngineConfig(enabled=False))),
            "dia": DiaTTSAdapter(engines.get("dia", TTSEngineConfig(enabled=False))),
            "orpheus": OrpheusTTSAdapter(engines.get("orpheus", TTSEngineConfig(enabled=False))),
            "mock": MockTTSAdapter(),
        }

    def status(self) -> dict:
        active = self.active_adapter()
        return {
            "primary": self.config.primary,
            "fallback": self.config.fallback,
            "active": active.name,
            "adapters": {name: adapter.health_check() for name, adapter in self.adapters.items()},
        }

    def active_adapter(self) -> TTSAdapter:
        for name in [self.config.primary, self.config.fallback, "kokoro", "mock"]:
            adapter = self.adapters.get(name)
            if adapter and adapter.is_available():
                return adapter
        return self.adapters["mock"]

    async def generate(self, text: str, voice: str | None = None, style: str | None = None, speed: float | None = None) -> AudioResult:
        async with self._lock:
            requested_voice = voice or self.config.voice
            requested_style = style or self.config.style
            requested_speed = speed if speed is not None else self.config.speed
            primary = self.adapters.get(self.config.primary)
            fallback = self.adapters.get(self.config.fallback)
            candidates = [primary, fallback, self.adapters.get("kokoro"), self.adapters["mock"]]
            last_error: Exception | None = None
            for adapter in candidates:
                if adapter is None or not adapter.is_available():
                    continue
                try:
                    return await adapter.generate(
                        text,
                        voice=requested_voice,
                        style=requested_style,
                        speed=requested_speed,
                    )
                except Exception as exc:
                    last_error = exc
                    continue
            if last_error:
                raise last_error
            return await self.adapters["mock"].generate(text, voice=requested_voice, style=requested_style)

    def stop(self) -> None:
        for adapter in self.adapters.values():
            adapter.stop()
