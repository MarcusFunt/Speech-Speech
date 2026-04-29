from local_assistant.config import TTSConfig, TTSEngineConfig
from local_assistant.tts.manager import TTSManager


def test_default_tts_config_prefers_chatterbox_with_kokoro_fallback():
    config = TTSConfig()
    assert config.primary == "chatterbox"
    assert config.fallback == "kokoro"
    assert config.engines["chatterbox"].enabled is True
    assert config.engines["chatterbox"].device == "cpu"


def test_tts_manager_falls_back_to_mock_when_real_engines_missing():
    manager = TTSManager(
        TTSConfig(
            primary="chatterbox",
            fallback="kokoro",
            engines={
                "chatterbox": TTSEngineConfig(enabled=False),
                "kokoro": TTSEngineConfig(enabled=False),
                "mock": TTSEngineConfig(enabled=True),
            },
        )
    )
    assert manager.active_adapter().name == "mock"


def test_tts_status_includes_fallback():
    manager = TTSManager(TTSConfig(primary="mock", fallback="kokoro"))
    status = manager.status()
    assert status["primary"] == "mock"
    assert "kokoro" in status["adapters"]
