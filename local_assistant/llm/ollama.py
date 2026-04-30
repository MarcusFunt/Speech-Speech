from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from local_assistant.config import LLMConfig
from local_assistant.llm.base import LLMAdapter


def ollama_native_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3]
    return normalized


def ollama_models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def ollama_native_models_url(base_url: str) -> str:
    return f"{ollama_native_base_url(base_url)}/api/tags"


def ollama_chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def ollama_native_chat_url(base_url: str) -> str:
    return f"{ollama_native_base_url(base_url)}/api/chat"


class OllamaLLMAdapter(LLMAdapter):
    name = "ollama"

    def __init__(self, config: LLMConfig):
        self.config = config

    async def health_check(self) -> dict:
        timeout = httpx.Timeout(3.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            openai_url = ollama_models_url(self.config.base_url)
            native_url = ollama_native_models_url(self.config.base_url)
            try:
                response = await client.get(openai_url)
                if response.is_success:
                    return {
                        "name": self.name,
                        "available": True,
                        "base_url": self.config.base_url,
                        "model": self.config.model,
                        "api": "openai_compatible",
                        "status_code": response.status_code,
                    }
                openai_status_code = response.status_code
            except Exception as exc:
                openai_status_code = None
                openai_error = str(exc)
            else:
                openai_error = None

            try:
                response = await client.get(native_url)
                return {
                    "name": self.name,
                    "available": response.is_success,
                    "base_url": self.config.base_url,
                    "model": self.config.model,
                    "api": "native",
                    "status_code": response.status_code,
                    "openai_status_code": openai_status_code,
                    "openai_error": openai_error,
                }
            except Exception as exc:
                return {
                    "name": self.name,
                    "available": False,
                    "base_url": self.config.base_url,
                    "model": self.config.model,
                    "api": "native",
                    "openai_status_code": openai_status_code,
                    "openai_error": openai_error,
                    "error": str(exc),
                }

    async def stream_chat(self, messages: list[dict[str, str]], cancel_event) -> AsyncIterator[str]:
        try:
            async for delta in self._stream_openai(messages, cancel_event):
                yield delta
            return
        except httpx.HTTPStatusError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise
        async for delta in self._stream_native(messages, cancel_event):
            yield delta

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            return {}
        return {"Authorization": f"Bearer {self.config.api_key}"}

    async def _stream_openai(
        self, messages: list[dict[str, str]], cancel_event
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        url = ollama_chat_completions_url(self.config.base_url)
        timeout = httpx.Timeout(self.config.timeout_s, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        return
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content

    async def _stream_native(
        self, messages: list[dict[str, str]], cancel_event
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }
        url = ollama_native_chat_url(self.config.base_url)
        timeout = httpx.Timeout(self.config.timeout_s, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        return
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise RuntimeError(event["error"])
                    message = event.get("message") or {}
                    content = message.get("content")
                    if content:
                        yield content
                    if event.get("done"):
                        return
