import asyncio

import httpx

from local_assistant.config import LLMConfig
from local_assistant.llm.manager import LLMManager
from local_assistant.llm.ollama import OllamaLLMAdapter


class FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str] | None = None, *, request: httpx.Request):
        self.status_code = status_code
        self._lines = lines or []
        self.request = request

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=self.request,
                response=self,
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeStreamContext:
    def __init__(self, response: FakeStreamResponse):
        self.response = response

    async def __aenter__(self) -> FakeStreamResponse:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeAsyncClient:
    get_handlers: dict[str, tuple[int, list[str] | None]] = {}
    stream_handlers: dict[str, tuple[int, list[str] | None]] = {}
    stream_calls: list[tuple[str, str, dict, dict]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str):
        status_code, lines = self.get_handlers[url]
        return FakeStreamResponse(status_code, lines, request=httpx.Request("GET", url))

    def stream(self, method: str, url: str, json=None, headers=None):
        self.stream_calls.append((method, url, json or {}, headers or {}))
        status_code, lines = self.stream_handlers[url]
        response = FakeStreamResponse(status_code, lines, request=httpx.Request(method, url))
        return FakeStreamContext(response)


def test_llm_manager_uses_ollama_adapter_for_ollama_provider():
    manager = LLMManager(LLMConfig(provider="ollama"))

    assert isinstance(manager.primary, OllamaLLMAdapter)


async def test_ollama_adapter_falls_back_to_native_chat_when_openai_chat_404(monkeypatch):
    base_url = "http://localhost:11434/v1"
    FakeAsyncClient.get_handlers = {}
    FakeAsyncClient.stream_calls = []
    FakeAsyncClient.stream_handlers = {
        "http://localhost:11434/v1/chat/completions": (404, []),
        "http://localhost:11434/api/chat": (
            200,
            [
                '{"message":{"content":"Hello "},"done":false}',
                '{"message":{"content":"there"},"done":false}',
                '{"done":true}',
            ],
        ),
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = OllamaLLMAdapter(LLMConfig(provider="ollama", base_url=base_url, model="qwen3:4b-instruct"))
    cancel_event = asyncio.Event()

    chunks = [chunk async for chunk in adapter.stream_chat([{"role": "user", "content": "Hi"}], cancel_event)]

    assert "".join(chunks) == "Hello there"
    assert [call[1] for call in FakeAsyncClient.stream_calls] == [
        "http://localhost:11434/v1/chat/completions",
        "http://localhost:11434/api/chat",
    ]
    native_payload = FakeAsyncClient.stream_calls[1][2]
    assert native_payload["stream"] is True
    assert native_payload["options"]["num_predict"] == 420


async def test_ollama_health_check_falls_back_to_native_tags(monkeypatch):
    base_url = "http://localhost:11434/v1"
    FakeAsyncClient.get_handlers = {
        "http://localhost:11434/v1/models": (404, []),
        "http://localhost:11434/api/tags": (200, []),
    }
    FakeAsyncClient.stream_calls = []
    FakeAsyncClient.stream_handlers = {}
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = OllamaLLMAdapter(LLMConfig(provider="ollama", base_url=base_url, model="qwen3:4b-instruct"))

    health = await adapter.health_check()

    assert health["available"] is True
    assert health["api"] == "native"
    assert health["status_code"] == 200
    assert health["openai_status_code"] == 404
