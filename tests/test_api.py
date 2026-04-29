from fastapi.testclient import TestClient

from local_assistant import server
from local_assistant.config import AppConfig, LLMConfig, MemoryConfig, STTConfig, TTSConfig
from local_assistant.stt.faster_whisper_adapter import FasterWhisperSTTAdapter


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


def test_mock_conversation_path(tmp_path):
    configure_test_services(tmp_path)
    client = TestClient(server.app)
    response = client.post("/conversation/message", json={"text": "Say hi."})
    assert response.status_code == 200
    payload = response.json()
    assert "debug mode" in payload["assistant_text"]
    assert any(event["type"] == "audio_chunk" for event in payload["events"])
