from __future__ import annotations

import asyncio
import base64
import time
import uuid
from typing import AsyncIterator

from local_assistant.config import AppConfig
from local_assistant.conversation.chunker import SpeechChunker
from local_assistant.conversation.prompt import build_messages
from local_assistant.conversation.sanitize import sanitize_for_speech
from local_assistant.llm.base import LLMAdapter
from local_assistant.memory.store import MemoryStore
from local_assistant.tts.manager import TTSManager


class ConversationManager:
    def __init__(self, config: AppConfig, memory: MemoryStore, llm: LLMAdapter, tts: TTSManager):
        self.config = config
        self.memory = memory
        self.llm = llm
        self.tts = tts
        self._cancel_event = asyncio.Event()
        self._current_turn_id: str | None = None

    def interrupt(self) -> str | None:
        self._cancel_event.set()
        self.tts.stop()
        return self._current_turn_id

    async def run_turn(self, user_text: str) -> AsyncIterator[dict]:
        self._cancel_event = asyncio.Event()
        self._current_turn_id = str(uuid.uuid4())
        turn_id = self._current_turn_id
        first_audio_at: float | None = None
        started_at = time.perf_counter()
        assistant_parts: list[str] = []
        chunker = SpeechChunker(
            min_chars=self.config.conversation.chunker.min_chars,
            max_chars=self.config.conversation.chunker.max_chars,
            low_latency_chars=self.config.conversation.chunker.low_latency_chars,
        )

        self.memory.add_turn("user", user_text)
        yield {"type": "state", "state": "thinking", "turn_id": turn_id}
        yield {"type": "transcript", "role": "user", "text": user_text, "turn_id": turn_id}

        active_tts = self.tts.active_adapter()
        messages = build_messages(
            config=self.config,
            user_text=user_text,
            profile=self.memory.get_profile(),
            relevant_memories=self.memory.search_memories(user_text, limit=6),
            recent_turns=self.memory.recent_turns(limit=self.config.conversation.max_recent_turns),
            tts_supports_nonverbals=active_tts.features.supports_nonverbals,
        )

        yield {"type": "state", "state": "speaking", "turn_id": turn_id}
        try:
            async for delta in self.llm.stream_chat(messages, self._cancel_event):
                if self._cancel_event.is_set():
                    yield {"type": "interrupted", "turn_id": turn_id}
                    return
                assistant_parts.append(delta)
                yield {"type": "text_delta", "delta": delta, "turn_id": turn_id}
                for chunk in chunker.feed(delta):
                    async for event in self._speak_chunk(chunk, turn_id):
                        if first_audio_at is None and event["type"] == "audio_chunk":
                            first_audio_at = time.perf_counter()
                            event["time_to_first_audio_ms"] = int((first_audio_at - started_at) * 1000)
                        yield event

            for chunk in chunker.flush():
                async for event in self._speak_chunk(chunk, turn_id):
                    if first_audio_at is None and event["type"] == "audio_chunk":
                        first_audio_at = time.perf_counter()
                        event["time_to_first_audio_ms"] = int((first_audio_at - started_at) * 1000)
                    yield event

            assistant_text = "".join(assistant_parts).strip()
            if assistant_text:
                self.memory.add_turn("assistant", assistant_text)
                yield {"type": "transcript", "role": "assistant", "text": assistant_text, "turn_id": turn_id}
            yield {
                "type": "done",
                "turn_id": turn_id,
                "time_to_first_audio_ms": int((first_audio_at - started_at) * 1000) if first_audio_at else None,
            }
        except Exception as exc:
            yield {"type": "error", "message": str(exc), "turn_id": turn_id}
        finally:
            yield {"type": "state", "state": "idle", "turn_id": turn_id}

    async def _speak_chunk(self, chunk: str, turn_id: str) -> AsyncIterator[dict]:
        if self._cancel_event.is_set():
            return
        spoken_chunk = sanitize_for_speech(chunk)
        if not spoken_chunk:
            return
        result = await self.tts.generate(spoken_chunk)
        if self._cancel_event.is_set():
            return
        yield {
            "type": "audio_chunk",
            "turn_id": turn_id,
            "text": spoken_chunk,
            "engine": result.engine,
            "voice": result.voice,
            "media_type": result.media_type,
            "sample_rate": result.sample_rate,
            "audio_base64": base64.b64encode(result.audio).decode("ascii"),
        }
