import socket

from local_assistant.dev import find_free_port, ollama_models_url, port_is_free
from local_assistant.server import allowed_cors_origins


def test_find_free_port_skips_occupied_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        occupied = sock.getsockname()[1]

        assert port_is_free("127.0.0.1", occupied) is False
        free_port = find_free_port("127.0.0.1", occupied)
        assert free_port != occupied
        assert port_is_free("127.0.0.1", free_port) is True


def test_allowed_cors_origins_includes_env_values(monkeypatch):
    monkeypatch.setenv(
        "LOCAL_ASSISTANT_CORS_ORIGINS",
        "http://127.0.0.1:5174, http://localhost:5174",
    )

    origins = allowed_cors_origins()

    assert "http://127.0.0.1:5174" in origins
    assert "http://localhost:5174" in origins


def test_ollama_models_url_uses_configured_openai_compatible_base():
    assert ollama_models_url("http://localhost:11434/v1") == "http://localhost:11434/v1/models"
    assert ollama_models_url("http://localhost:11434/v1/") == "http://localhost:11434/v1/models"
