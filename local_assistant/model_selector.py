from __future__ import annotations

from local_assistant.config import AppConfig, LLMConfig, STTConfig, TTSConfig, TTSEngineConfig
from local_assistant.hardware_probe import HardwareProfile


def _base_tts_engines(device: str) -> dict[str, TTSEngineConfig]:
    return {
        "kokoro": TTSEngineConfig(
            enabled=True,
            model="Kokoro-82M",
            device=device,
            default_voice="af_heart",
            extra={"lang_code": "a"},
        ),
        "chatterbox": TTSEngineConfig(enabled=False, model="chatterbox-tts", device=device),
        "dia": TTSEngineConfig(enabled=False, model="dia", device=device),
        "orpheus": TTSEngineConfig(enabled=False, model="orpheus", device=device),
        "mock": TTSEngineConfig(enabled=True, device="cpu"),
    }


def select_config(profile: HardwareProfile) -> AppConfig:
    device = "cuda" if profile.gpu_backend == "cuda" and profile.cuda_available else "cpu"
    selected_profile = profile.recommended_profile
    tts_primary = "kokoro"
    tts_fallback = "kokoro"
    engines = _base_tts_engines(device)

    stt_model = "base"
    stt_compute_type = "float16" if device == "cuda" else "int8"
    llm_model = "qwen3:4b-instruct"

    if profile.gpu_backend == "cuda" and (profile.vram_gb or 0) >= 12:
        selected_profile = "high"
        tts_primary = "chatterbox"
        engines["chatterbox"].enabled = True
        engines["dia"].enabled = True
        engines["orpheus"].enabled = True
        stt_model = "small"
        llm_model = "qwen3:8b"
    elif profile.gpu_backend == "cuda" and (profile.vram_gb or 0) >= 6:
        selected_profile = "medium"
        tts_primary = "chatterbox"
        engines["chatterbox"].enabled = True
        stt_model = "base"
        llm_model = "qwen3:4b-instruct"
    elif profile.gpu_backend == "mps":
        selected_profile = "medium"
        engines["kokoro"].device = "mps"
        stt_model = "base"
    elif profile.gpu_backend in {"rocm", "unknown"}:
        selected_profile = "low"
        tts_primary = "kokoro"
        stt_model = "base"
    else:
        selected_profile = "low"
        stt_model = "tiny" if (profile.ram_gb or 0) < 8 else "base"

    return AppConfig(
        selected_profile=selected_profile,
        hardware_profile=profile.model_dump(mode="json"),
        stt=STTConfig(
            provider="faster_whisper",
            model=stt_model,
            device=device,
            compute_type=stt_compute_type,
            vad_filter=False,
        ),
        llm=LLMConfig(provider="ollama", model=llm_model),
        tts=TTSConfig(
            primary=tts_primary,
            fallback=tts_fallback,
            voice="af_heart",
            style="natural",
            speed=1.0,
            engines=engines,
        ),
    )
