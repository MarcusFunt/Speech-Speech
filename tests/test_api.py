from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from local_assistant import server
from local_assistant.conversation.manager import ConversationManager
from local_assistant.config import AppConfig, LLMConfig, MemoryConfig, STTConfig, TTSConfig, load_config, save_config
from local_assistant.hardware_probe import HardwareProfile
from local_assistant.memory.store import MemoryStore
from local_assistant.stt.faster_whisper_adapter import FasterWhisperSTTAdapter
from local_assistant.tts.manager import TTSManager


class CapturingLLM:
    name = "capturing"
    used_fallback = False

    def __init__(self):
        self.messages = []

    async def health_check(self):
        return {"name": self.name, "available": True}

    async def stream_chat(self, messages, _cancel_event):
        self.messages = messages
        yield "captured."


def configure_test_services(tmp_path):
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        tts=TTSConfig(primary="mock", fallback="mock"),
        memory=MemoryConfig(db_path=str(tmp_path / "memory.sqlite3")),
    )
    server._services = server.create_services(config)


def test_health_endpoint(tmp_path):
    configure_test_services(tmp_path)
    client = TestClient(server.app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tts"]["active"] == "mock"


def test_mock_stt_transcribes_configured_debug_text(tmp_path):
    config = AppConfig(
        stt=STTConfig(provider="mock", mock_transcript="debug transcript", mock_language="en"),
        llm=LLMConfig(provider="mock"),
        tts=TTSConfig(primary="mock", fallback="mock"),
        memory=MemoryConfig(db_path=str(tmp_path / "memory.sqlite3")),
    )
    server._services = server.create_services(config)
    client = TestClient(server.app)

    response = client.post(
        "/stt/transcribe",
        files={"file": ("sample.webm", b"not-empty-audio", "audio/webm")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "debug transcript"
    assert payload["language"] == "en"
    assert payload["backend"] == "mock"


def test_real_stt_unavailable_returns_service_error(tmp_path, monkeypatch):
    monkeypatch.setattr(FasterWhisperSTTAdapter, "is_available", lambda self: False)
    config = AppConfig(
        stt=STTConfig(provider="faster_whisper"),
        llm=LLMConfig(provider="mock"),
        tts=TTSConfig(primary="mock", fallback="mock"),
        memory=MemoryConfig(db_path=str(tmp_path / "memory.sqlite3")),
    )
    server._services = server.create_services(config)
    client = TestClient(server.app)

    response = client.post(
        "/stt/transcribe",
        files={"file": ("sample.webm", b"not-empty-audio", "audio/webm")},
    )

    assert response.status_code == 503
    assert "faster-whisper is not installed" in response.json()["detail"]


def test_memory_endpoints(tmp_path):
    configure_test_services(tmp_path)
    client = TestClient(server.app)
    response = client.post("/memory", json={"kind": "episodic", "content": "Remember this."})
    assert response.status_code == 200
    memory_id = response.json()["memory"]["id"]
    assert client.get("/memory").json()["memories"][0]["content"] == "Remember this."
    assert client.delete(f"/memory/{memory_id}").status_code == 200


def test_frontend_routes_serve_static_files_and_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok');", encoding="utf-8")

    app = FastAPI()
    server.install_frontend_routes(app, dist)
    client = TestClient(app)

    assert client.get("/").text == "<html>app</html>"
    assert client.get("/settings/profile").text == "<html>app</html>"
    assert client.get("/assets/app.js").text == "console.log('ok');"


def test_mock_conversation_path(tmp_path):
    configure_test_services(tmp_path)
    client = TestClient(server.app)
    response = client.post("/conversation/message", json={"text": "Say hi."})
    assert response.status_code == 200
    payload = response.json()
    assert "debug mode" in payload["assistant_text"]
    assert any(event["type"] == "audio_chunk" for event in payload["events"])


@pytest.mark.asyncio
async def test_conversation_prompt_does_not_duplicate_current_user_turn(tmp_path):
    config = AppConfig(
        llm=LLMConfig(provider="mock"),
        tts=TTSConfig(primary="mock", fallback="mock"),
        memory=MemoryConfig(db_path=str(tmp_path / "memory.sqlite3")),
    )
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    llm = CapturingLLM()
    conversation = ConversationManager(config=config, memory=memory, llm=llm, tts=TTSManager(config.tts))

    events = [event async for event in conversation.run_turn("current request")]

    assert any(event["type"] == "done" for event in events)
    assert [message for message in llm.messages if message["content"] == "current request"] == [
        {"role": "user", "content": "current request"}
    ]


@pytest.mark.asyncio
async def test_replace_services_validates_before_saving(tmp_path, monkeypatch):
    original_config = AppConfig(
        stt=STTConfig(provider="mock"),
        llm=LLMConfig(provider="mock"),
        tts=TTSConfig(primary="mock", fallback="mock"),
        memory=MemoryConfig(db_path=str(tmp_path / "original.sqlite3")),
    )
    original_services = server.create_services(original_config)
    server._services = original_services
    saves = []

    def fail_create_services(_config):
        raise RuntimeError("bad config")

    monkeypatch.setattr(server, "create_services", fail_create_services)
    monkeypatch.setattr(server, "save_config", lambda *args, **kwargs: saves.append((args, kwargs)))

    with pytest.raises(RuntimeError, match="bad config"):
        await server.replace_services(
            AppConfig(
                stt=STTConfig(provider="mock"),
                llm=LLMConfig(provider="mock"),
                tts=TTSConfig(primary="mock", fallback="mock"),
                memory=MemoryConfig(db_path=str(tmp_path / "next.sqlite3")),
            )
        )

    assert server._services is original_services
    assert saves == []


def test_config_reset_autoselects_and_backs_up_existing_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    original_config = AppConfig(
        selected_profile="manual",
        stt=STTConfig(provider="mock"),
        llm=LLMConfig(provider="mock"),
        tts=TTSConfig(primary="mock", fallback="mock"),
        memory=MemoryConfig(db_path=str(tmp_path / "manual.sqlite3")),
    )
    selected_config = AppConfig(
        selected_profile="auto",
        stt=STTConfig(provider="mock"),
        llm=LLMConfig(provider="mock"),
        tts=TTSConfig(primary="mock", fallback="mock"),
        memory=MemoryConfig(db_path=str(tmp_path / "auto.sqlite3")),
    )
    profile = HardwareProfile(
        os_name="Windows",
        os_version="test",
        cpu_cores=8,
        ram_gb=16,
        python_version="3.11.9",
        gpu_backend="cpu",
        recommended_profile="low",
    )

    save_config(original_config, config_path)
    server._services = server.create_services(original_config)
    monkeypatch.setattr(server, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(server, "probe_hardware", lambda: profile)
    monkeypatch.setattr(server, "select_config", lambda _profile: selected_config)

    client = TestClient(server.app)
    response = client.post("/config/reset")

    assert response.status_code == 200
    assert response.json()["selected_profile"] == "auto"
    backups = list(tmp_path.glob("config.yaml.*.bak"))
    assert len(backups) == 1
    assert load_config(backups[0]).selected_profile == "manual"
    assert load_config(config_path).selected_profile == "auto"
