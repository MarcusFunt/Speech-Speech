from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import importlib.util
import inspect
import io
import threading
from pathlib import Path
from typing import Any

import numpy as np

from local_assistant.config import TTSEngineConfig, resolve_project_path
from local_assistant.tts.base import AudioResult, TTSAdapter, TTSFeatures


_REQUIRED_PACKAGES = ("chatterbox", "torch", "soundfile")
_VARIANT_CLASSES = {
    "turbo": ("chatterbox.tts_turbo", "ChatterboxTurboTTS"),
    "multilingual": ("chatterbox.mtl_tts", "ChatterboxMultilingualTTS"),
    "standard": ("chatterbox.tts", "ChatterboxTTS"),
}
_VOICE_FILE_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
_GENERATION_KEYS = {
    "exaggeration",
    "cfg_weight",
    "temperature",
    "repetition_penalty",
    "min_p",
    "top_p",
    "top_k",
    "norm_loudness",
}
_MULTILINGUAL_LANGUAGE_CODES = {
    "ar",
    "da",
    "de",
    "el",
    "en",
    "es",
    "fi",
    "fr",
    "he",
    "hi",
    "it",
    "ja",
    "ko",
    "ms",
    "nl",
    "no",
    "pl",
    "pt",
    "ru",
    "sv",
    "sw",
    "tr",
    "zh",
}


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
        self._resolved_variant: str | None = None
        self._sample_rate = 24000
        self._load_error: str | None = None
        self._stopped = False
        self._model_lock = threading.RLock()

    def is_available(self) -> bool:
        return self.config.enabled and not self._load_error and not self._missing_requirements()

    def health_check(self) -> dict:
        missing = self._missing_requirements()
        return {
            "name": self.name,
            "available": self.is_available(),
            "model": self.config.model,
            "variant": self._configured_variant(),
            "resolved_variant": self._resolved_variant,
            "device": self._configured_device(),
            "default_voice": self.config.default_voice,
            "package_version": self._package_version(),
            "loaded": self._model is not None,
            "sample_rate": self._sample_rate,
            "load_error": self._load_error,
            "missing": missing,
            "needs": ["chatterbox-tts", "torch", "soundfile"],
        }

    async def generate(
        self,
        text: str,
        voice: str | None = None,
        style: str | None = None,
        speed: float = 1.0,
    ) -> AudioResult:
        if not self.is_available():
            raise RuntimeError(self._unavailable_message())
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Chatterbox requires non-empty text")
        self._stopped = False
        return await asyncio.to_thread(self._generate_sync, clean_text, voice, style, speed)

    def _generate_sync(self, text: str, voice: str | None, style: str | None, speed: float) -> AudioResult:
        model = self._get_model()
        prompt_path = self._resolve_voice_prompt(voice)
        kwargs = self._generation_kwargs(style=style, audio_prompt_path=prompt_path)
        wav = self._call_generate(model, text, kwargs)
        samples = self._audio_to_numpy(wav)
        samples = self._apply_speed(samples, speed)
        audio = self._encode_wav(samples, self._sample_rate)
        return AudioResult(
            audio=audio,
            media_type="audio/wav",
            sample_rate=self._sample_rate,
            engine=self.name,
            voice=str(prompt_path) if prompt_path else voice,
        )

    def stop(self) -> None:
        self._stopped = True

    def _get_model(self):
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                variant = self._resolve_variant()
                module_name, class_name = _VARIANT_CLASSES[variant]
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
                checkpoint_dir = self._checkpoint_dir()
                if checkpoint_dir:
                    self._model = cls.from_local(str(checkpoint_dir), device=self._configured_device())
                else:
                    self._model = cls.from_pretrained(device=self._configured_device())
                self._resolved_variant = variant
                self._sample_rate = int(getattr(self._model, "sr", 24000))
                self._load_error = None
            except Exception as exc:
                self._load_error = str(exc)
                raise RuntimeError(f"Could not load Chatterbox TTS: {exc}") from exc
            return self._model

    def _resolve_variant(self) -> str:
        configured = self._configured_variant()
        if configured != "auto":
            self._require_variant_module(configured)
            return configured
        for variant in ("turbo", "standard"):
            if self._module_available(_VARIANT_CLASSES[variant][0]):
                return variant
        self._require_variant_module("standard")
        return "standard"

    def _configured_variant(self) -> str:
        value = str(self.config.extra.get("variant") or self.config.model or "").strip().lower()
        if not value or value in {"chatterbox-tts", "auto"}:
            return "auto"
        if "turbo" in value:
            return "turbo"
        if "multi" in value or "mtl" in value:
            return "multilingual"
        if value in {"standard", "original", "base", "english", "chatterbox"}:
            return "standard"
        return "auto"

    def _configured_device(self) -> str:
        device = str(self.config.device or "cpu").strip().lower()
        if device != "auto":
            return device
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            return "cpu"
        return "cpu"

    def _checkpoint_dir(self) -> Path | None:
        value = (
            self.config.extra.get("checkpoint_dir")
            or self.config.extra.get("ckpt_dir")
            or self.config.extra.get("local_path")
        )
        if not value:
            return None
        path = resolve_project_path(str(value))
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Configured Chatterbox checkpoint directory does not exist: {path}")
        return path

    def _generation_kwargs(self, *, style: str | None, audio_prompt_path: Path | None) -> dict[str, Any]:
        variant = self._resolved_variant or self._resolve_variant()
        kwargs = self._base_generation_defaults(variant)
        for key in _GENERATION_KEYS:
            if key in self.config.extra:
                kwargs[key] = self.config.extra[key]
        kwargs.update(self._style_generation_overrides(style, variant))
        if audio_prompt_path:
            kwargs["audio_prompt_path"] = str(audio_prompt_path)
        if variant == "multilingual":
            kwargs["language_id"] = self._language_id(style)
        return kwargs

    def _base_generation_defaults(self, variant: str) -> dict[str, Any]:
        if variant == "turbo":
            return {
                "temperature": 0.8,
                "top_k": 1000,
                "top_p": 0.95,
                "repetition_penalty": 1.2,
                "norm_loudness": True,
            }
        if variant == "multilingual":
            return {
                "exaggeration": 0.5,
                "cfg_weight": 0.5,
                "temperature": 0.8,
                "repetition_penalty": 2.0,
                "min_p": 0.05,
                "top_p": 1.0,
            }
        return {
            "exaggeration": 0.5,
            "cfg_weight": 0.5,
            "temperature": 0.8,
            "repetition_penalty": 1.2,
            "min_p": 0.05,
            "top_p": 1.0,
        }

    def _style_generation_overrides(self, style: str | None, variant: str) -> dict[str, Any]:
        normalized = (style or "").strip().lower()
        if variant == "turbo":
            if normalized in {"calm", "soft"}:
                return {"temperature": 0.7, "top_p": 0.9}
            if normalized in {"energetic", "lively", "dramatic"}:
                return {"temperature": 0.9, "top_p": 0.98}
            return {}
        if normalized in {"calm", "soft"}:
            return {"exaggeration": 0.35, "cfg_weight": 0.55, "temperature": 0.7}
        if normalized in {"expressive", "emotional", "lively"}:
            return {"exaggeration": 0.65, "cfg_weight": 0.35, "temperature": 0.85}
        if normalized == "dramatic":
            return {"exaggeration": 0.8, "cfg_weight": 0.3, "temperature": 0.9}
        return {}

    def _language_id(self, style: str | None) -> str:
        explicit = self.config.extra.get("language_id") or self.config.extra.get("language")
        if explicit:
            return str(explicit).lower()
        normalized_style = (style or "").strip().lower()
        if normalized_style in _MULTILINGUAL_LANGUAGE_CODES:
            return normalized_style
        return "en"

    def _call_generate(self, model: Any, text: str, kwargs: dict[str, Any]) -> Any:
        signature = inspect.signature(model.generate)
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
        if not accepts_kwargs:
            kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
        return model.generate(text, **kwargs)

    def _resolve_voice_prompt(self, voice: str | None) -> Path | None:
        voice_prompts = self.config.extra.get("voices") or self.config.extra.get("voice_prompts") or {}
        candidates = [
            voice_prompts.get(voice) if isinstance(voice_prompts, dict) and voice else None,
            voice,
            self.config.extra.get("audio_prompt_path"),
            self.config.extra.get("voice_prompt_path"),
            self.config.default_voice,
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = resolve_project_path(str(candidate))
            if path.exists() and path.is_file():
                return path
            if self._looks_like_path(str(candidate)):
                raise FileNotFoundError(f"Chatterbox voice prompt does not exist: {path}")
        return None

    def _looks_like_path(self, value: str) -> bool:
        path = Path(value)
        return any(separator in value for separator in ("/", "\\")) or path.suffix.lower() in _VOICE_FILE_SUFFIXES

    def _audio_to_numpy(self, wav: Any) -> np.ndarray:
        if hasattr(wav, "detach"):
            wav = wav.detach()
        if hasattr(wav, "cpu"):
            wav = wav.cpu()
        if hasattr(wav, "numpy"):
            wav = wav.numpy()
        samples = np.asarray(wav)
        if samples.size == 0:
            raise RuntimeError("Chatterbox generated no audio")
        if samples.ndim == 0:
            raise RuntimeError("Chatterbox returned invalid scalar audio")
        samples = np.squeeze(samples)
        if samples.ndim > 2:
            raise RuntimeError(f"Chatterbox returned unsupported audio shape: {samples.shape}")
        if samples.ndim == 2 and samples.shape[0] <= 8 and samples.shape[0] < samples.shape[1]:
            samples = samples.T
        samples = samples.astype(np.float32, copy=False)
        return np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)

    def _apply_speed(self, samples: np.ndarray, speed: float) -> np.ndarray:
        if speed <= 0:
            raise ValueError("TTS speed must be greater than zero")
        if abs(speed - 1.0) < 0.01:
            return samples
        try:
            import librosa
        except Exception as exc:
            raise RuntimeError("Chatterbox speed control requires librosa") from exc
        rate = max(0.5, min(2.0, float(speed)))
        if samples.ndim == 1:
            return librosa.effects.time_stretch(samples, rate=rate).astype(np.float32, copy=False)
        channels = [librosa.effects.time_stretch(samples[:, idx], rate=rate) for idx in range(samples.shape[1])]
        min_len = min(len(channel) for channel in channels)
        return np.stack([channel[:min_len] for channel in channels], axis=1).astype(np.float32, copy=False)

    def _encode_wav(self, samples: np.ndarray, sample_rate: int) -> bytes:
        import soundfile as sf

        clipped = np.clip(samples, -1.0, 1.0)
        buffer = io.BytesIO()
        sf.write(buffer, clipped, sample_rate, format="WAV", subtype="PCM_16")
        return buffer.getvalue()

    def _missing_requirements(self) -> list[str]:
        missing = [package for package in _REQUIRED_PACKAGES if not self._module_available(package)]
        configured = self._configured_variant()
        if configured != "auto":
            module_name = _VARIANT_CLASSES[configured][0]
            if not self._module_available(module_name):
                missing.append(module_name)
        elif not any(self._module_available(_VARIANT_CLASSES[variant][0]) for variant in ("turbo", "standard")):
            missing.append("chatterbox.tts_turbo or chatterbox.tts")
        return missing

    def _require_variant_module(self, variant: str) -> None:
        module_name = _VARIANT_CLASSES[variant][0]
        if not self._module_available(module_name):
            raise RuntimeError(f"Chatterbox variant '{variant}' is unavailable because {module_name} is not installed")

    def _module_available(self, module_name: str) -> bool:
        try:
            return importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    def _package_version(self) -> str | None:
        try:
            return importlib.metadata.version("chatterbox-tts")
        except importlib.metadata.PackageNotFoundError:
            return None

    def _unavailable_message(self) -> str:
        if not self.config.enabled:
            return "Chatterbox is not enabled"
        missing = self._missing_requirements()
        if missing:
            return f"Chatterbox is missing required packages: {', '.join(missing)}"
        if self._load_error:
            return f"Chatterbox failed to load: {self._load_error}"
        return "Chatterbox is unavailable"
