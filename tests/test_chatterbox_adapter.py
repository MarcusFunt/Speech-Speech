from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import types

import numpy as np
import pytest

from local_assistant.config import TTSEngineConfig
from local_assistant.tts.chatterbox_adapter import ChatterboxTTSAdapter


def install_fake_chatterbox(monkeypatch, module_name: str, class_name: str, fake_class: type) -> None:
    package = types.ModuleType("chatterbox")
    package.__path__ = []
    package.__spec__ = importlib.machinery.ModuleSpec("chatterbox", loader=None, is_package=True)
    module = types.ModuleType(module_name)
    module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None)
    setattr(module, class_name, fake_class)

    monkeypatch.setitem(sys.modules, "chatterbox", package)
    monkeypatch.setitem(sys.modules, module_name, module)

    available = {"chatterbox", "torch", "soundfile", module_name}
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, package: str | None = None):
        if name in available:
            return importlib.machinery.ModuleSpec(name, loader=None)
        return original_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)


@pytest.mark.asyncio
async def test_chatterbox_turbo_generates_real_wav_with_voice_prompt(tmp_path, monkeypatch):
    prompt = tmp_path / "reference.wav"
    prompt.write_bytes(b"placeholder")

    class FakeTurboTTS:
        instance = None

        def __init__(self, device: str):
            self.device = device
            self.sr = 24000
            self.calls: list[dict] = []

        @classmethod
        def from_pretrained(cls, device: str):
            cls.instance = cls(device)
            return cls.instance

        def generate(self, text: str, **kwargs):
            self.calls.append({"text": text, **kwargs})
            return np.sin(np.linspace(0, 1, 240, dtype=np.float32))[None, :]

    install_fake_chatterbox(monkeypatch, "chatterbox.tts_turbo", "ChatterboxTurboTTS", FakeTurboTTS)
    adapter = ChatterboxTTSAdapter(
        TTSEngineConfig(
            enabled=True,
            model="chatterbox-turbo",
            device="cpu",
            extra={"voices": {"clone": str(prompt)}, "temperature": 0.4, "top_k": 128},
        )
    )

    result = await adapter.generate("hello from chatterbox", voice="clone", style="natural")

    assert result.audio[:4] == b"RIFF"
    assert result.sample_rate == 24000
    assert result.engine == "chatterbox"
    assert result.voice == str(prompt)
    assert FakeTurboTTS.instance is not None
    assert FakeTurboTTS.instance.calls == [
        {
            "text": "hello from chatterbox",
            "temperature": 0.4,
            "top_k": 128,
            "top_p": 0.95,
            "repetition_penalty": 1.2,
            "norm_loudness": True,
            "audio_prompt_path": str(prompt),
        }
    ]


@pytest.mark.asyncio
async def test_chatterbox_multilingual_passes_configured_language(monkeypatch):
    class FakeMultilingualTTS:
        instance = None

        def __init__(self):
            self.sr = 22050
            self.calls: list[dict] = []

        @classmethod
        def from_pretrained(cls, device: str):
            cls.instance = cls()
            cls.instance.device = device
            return cls.instance

        def generate(self, text: str, language_id: str, **kwargs):
            self.calls.append({"text": text, "language_id": language_id, **kwargs})
            return np.zeros(128, dtype=np.float32)

    install_fake_chatterbox(
        monkeypatch,
        "chatterbox.mtl_tts",
        "ChatterboxMultilingualTTS",
        FakeMultilingualTTS,
    )
    adapter = ChatterboxTTSAdapter(
        TTSEngineConfig(
            enabled=True,
            model="chatterbox-multilingual",
            device="cpu",
            extra={"language_id": "fr", "cfg_weight": 0.25},
        )
    )

    result = await adapter.generate("bonjour", style="natural")

    assert result.audio[:4] == b"RIFF"
    assert result.sample_rate == 22050
    assert FakeMultilingualTTS.instance is not None
    assert FakeMultilingualTTS.instance.calls[0]["language_id"] == "fr"
    assert FakeMultilingualTTS.instance.calls[0]["cfg_weight"] == 0.25


@pytest.mark.asyncio
async def test_chatterbox_invalid_path_like_voice_fails_before_generation(monkeypatch):
    class FakeTurboTTS:
        @classmethod
        def from_pretrained(cls, device: str):
            instance = cls()
            instance.sr = 24000
            return instance

        def generate(self, text: str, **kwargs):
            raise AssertionError("generation should not run with a missing voice prompt")

    install_fake_chatterbox(monkeypatch, "chatterbox.tts_turbo", "ChatterboxTurboTTS", FakeTurboTTS)
    adapter = ChatterboxTTSAdapter(
        TTSEngineConfig(enabled=True, model="chatterbox-turbo", device="cpu")
    )

    with pytest.raises(FileNotFoundError, match="voice prompt does not exist"):
        await adapter.generate("hello", voice="missing-reference.wav")
