from local_assistant.hardware_probe import HardwareProfile
from local_assistant.model_selector import select_config


def profile(**overrides):
    values = {
        "os_name": "Windows",
        "os_version": "test",
        "cpu_cores": 8,
        "ram_gb": 16,
        "python_version": "3.11.9",
        "gpu_backend": "cpu",
        "recommended_profile": "low",
    }
    values.update(overrides)
    return HardwareProfile(**values)


def test_cpu_selects_kokoro_and_small_local_stack():
    config = select_config(profile())
    assert config.selected_profile == "low"
    assert config.tts.primary == "kokoro"
    assert config.tts.fallback == "kokoro"
    assert config.stt.device == "cpu"
    assert config.llm.provider == "ollama"


def test_cuda_8gb_selects_chatterbox_primary():
    config = select_config(
        profile(
            nvidia_gpu=True,
            cuda_available=True,
            gpu_backend="cuda",
            vram_gb=8,
            nvidia_vram_gb=8,
            recommended_profile="medium",
        )
    )
    assert config.selected_profile == "medium"
    assert config.tts.primary == "chatterbox"
    assert config.tts.engines["chatterbox"].enabled is True


def test_cuda_12gb_enables_experimental_tts():
    config = select_config(
        profile(
            nvidia_gpu=True,
            cuda_available=True,
            gpu_backend="cuda",
            vram_gb=16,
            nvidia_vram_gb=16,
            recommended_profile="high",
        )
    )
    assert config.selected_profile == "high"
    assert config.tts.engines["dia"].enabled is True
    assert config.tts.engines["orpheus"].enabled is True
