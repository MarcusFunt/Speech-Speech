from __future__ import annotations

import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from local_assistant.config import (
    AppConfig,
    DEFAULT_CONFIG_PATH,
    ensure_config,
    ensure_runtime_dirs,
    load_config,
    resolve_project_path,
    save_config,
)
from local_assistant.conversation.manager import ConversationManager
from local_assistant.hardware_probe import probe_hardware
from local_assistant.llm.manager import LLMManager
from local_assistant.memory.store import MemoryStore
from local_assistant.model_selector import select_config
from local_assistant.stt.base import STTError, STTUnavailableError
from local_assistant.stt.faster_whisper_adapter import FasterWhisperSTTAdapter
from local_assistant.stt.mock import MockSTTAdapter
from local_assistant.tts.manager import TTSManager


logger = logging.getLogger("local_assistant")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class MessageRequest(BaseModel):
    text: str = Field(min_length=1)


class TTSGenerateRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str | None = None
    style: str | None = None
    speed: float | None = None


class MemoryWriteRequest(BaseModel):
    kind: Literal["profile", "episodic", "summary"] = "episodic"
    key: str | None = None
    content: str
    tags: list[str] = Field(default_factory=list)


@dataclass
class Services:
    config: AppConfig
    memory: MemoryStore
    stt: Any
    llm: LLMManager
    tts: TTSManager
    conversation: ConversationManager


_services: Services | None = None
_services_lock = asyncio.Lock()


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def allowed_cors_origins() -> list[str]:
    origins: list[str] = []
    try:
        origins.extend(load_config(DEFAULT_CONFIG_PATH).server.cors_origins)
    except Exception as exc:
        logger.warning("Could not load configured CORS origins: %s", exc)
        origins.extend(AppConfig().server.cors_origins)
    origins.extend(_split_csv(os.getenv("LOCAL_ASSISTANT_CORS_ORIGINS")))
    return list(dict.fromkeys(origins))


def create_services(config: AppConfig) -> Services:
    ensure_runtime_dirs(config)
    memory = MemoryStore(resolve_project_path(config.memory.db_path))
    memory.seed_profile(
        {
            "assistant_name": config.memory.assistant_name,
            "personality": config.memory.personality,
            "speaking_style": config.memory.speaking_style,
            "user_preferences": config.memory.user_preferences,
        }
    )
    if config.stt.provider == "mock":
        stt = MockSTTAdapter(transcript=config.stt.mock_transcript, language=config.stt.mock_language)
    else:
        stt = FasterWhisperSTTAdapter(config.stt)
    llm = LLMManager(config.llm)
    tts = TTSManager(config.tts)
    conversation = ConversationManager(config=config, memory=memory, llm=llm, tts=tts)
    return Services(config=config, memory=memory, stt=stt, llm=llm, tts=tts, conversation=conversation)


async def get_services() -> Services:
    global _services
    if _services is None:
        async with _services_lock:
            if _services is None:
                _services = create_services(ensure_config(DEFAULT_CONFIG_PATH))
    return _services


async def replace_services(config: AppConfig) -> Services:
    global _services
    async with _services_lock:
        save_config(config, DEFAULT_CONFIG_PATH)
        _services = create_services(config)
        return _services


@asynccontextmanager
async def lifespan(_: FastAPI):
    await get_services()
    yield


app = FastAPI(title="Local Voice-to-Voice Assistant", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    services = await get_services()
    return {
        "ok": True,
        "profile": services.config.selected_profile,
        "stt": services.stt.health_check(),
        "llm": await services.llm.health_check(),
        "tts": services.tts.status(),
    }


@app.get("/hardware")
async def hardware() -> dict:
    return probe_hardware().model_dump(mode="json")


@app.get("/config")
async def get_config() -> dict:
    services = await get_services()
    return services.config.model_dump(mode="json")


@app.post("/config")
async def post_config(payload: AppConfig) -> dict:
    services = await replace_services(payload)
    return services.config.model_dump(mode="json")


@app.post("/config/autoselect")
async def autoselect_config() -> dict:
    profile = probe_hardware()
    config = select_config(profile)
    services = await replace_services(config)
    return services.config.model_dump(mode="json")


@app.post("/stt/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict:
    services = await get_services()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded audio was empty")
    try:
        result = await services.stt.transcribe(data, filename=file.filename or "input.webm")
    except STTUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except STTError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "text": result.text,
        "language": result.language,
        "duration_s": result.duration_s,
        "backend": result.backend,
    }


@app.post("/conversation/message")
async def conversation_message(payload: MessageRequest) -> dict:
    services = await get_services()
    events: list[dict] = []
    assistant_text_parts: list[str] = []
    async for event in services.conversation.run_turn(payload.text):
        events.append(event)
        if event["type"] == "text_delta":
            assistant_text_parts.append(event["delta"])
    return {"assistant_text": "".join(assistant_text_parts).strip(), "events": events}


@app.websocket("/conversation/stream")
async def conversation_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    services = await get_services()
    try:
        while True:
            payload = await websocket.receive_json()
            event_type = payload.get("type")
            if event_type == "interrupt":
                interrupted = services.conversation.interrupt()
                await websocket.send_json({"type": "interrupted", "turn_id": interrupted})
                continue
            if event_type == "user_audio":
                audio_base64 = payload.get("audio_base64", "")
                try:
                    audio = base64.b64decode(audio_base64)
                except ValueError:
                    await websocket.send_json({"type": "error", "message": "Invalid audio_base64"})
                    continue
                await websocket.send_json({"type": "state", "state": "transcribing"})
                try:
                    result = await services.stt.transcribe(audio, filename=payload.get("filename") or "input.webm")
                except STTError as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                user_text = result.text
            elif event_type == "user_text":
                user_text = str(payload.get("text") or "").strip()
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown event type: {event_type}"})
                continue

            if not user_text:
                await websocket.send_json({"type": "error", "message": "No text to process"})
                continue
            async for event in services.conversation.run_turn(user_text):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("Conversation websocket disconnected")


@app.post("/tts/generate")
async def tts_generate(payload: TTSGenerateRequest) -> Response:
    services = await get_services()
    result = await services.tts.generate(payload.text, voice=payload.voice, style=payload.style, speed=payload.speed)
    return Response(
        content=result.audio,
        media_type=result.media_type,
        headers={
            "X-TTS-Engine": result.engine,
            "X-TTS-Voice": result.voice or "",
            "X-Sample-Rate": str(result.sample_rate),
        },
    )


@app.post("/audio/interrupt")
async def audio_interrupt() -> dict:
    services = await get_services()
    interrupted = services.conversation.interrupt()
    return {"ok": True, "interrupted_turn_id": interrupted}


@app.get("/memory")
async def get_memory() -> dict:
    services = await get_services()
    return {
        "profile": services.memory.get_profile(),
        "memories": services.memory.list_memories(),
        "recent_turns": services.memory.recent_turns(),
    }


@app.post("/memory")
async def post_memory(payload: MemoryWriteRequest) -> dict:
    services = await get_services()
    if payload.kind == "profile":
        if not payload.key:
            raise HTTPException(status_code=400, detail="Profile writes require a key")
        return {"profile": services.memory.set_profile(payload.key, payload.content)}
    return {"memory": services.memory.add_memory(payload.kind, payload.content, payload.tags)}


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: int) -> dict:
    services = await get_services()
    deleted = services.memory.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}


def main() -> None:
    import uvicorn

    config = load_config(DEFAULT_CONFIG_PATH)
    uvicorn.run("local_assistant.server:app", host=config.server.host, port=config.server.port, reload=False)


if __name__ == "__main__":
    main()
