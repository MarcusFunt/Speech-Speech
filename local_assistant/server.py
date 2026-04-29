from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

from local_assistant.config import (
    AppConfig,
    DEFAULT_CONFIG_PATH,
    ROOT_DIR,
    apply_env_overrides,
    ensure_config,
    ensure_runtime_dirs,
    load_config,
    resolve_project_path,
    save_config,
)
from local_assistant.conversation.manager import ConversationManager
from local_assistant.errors import structured_error
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
ERROR_PAYLOAD_KEYS = {"code", "message", "hint", "retryable", "details"}


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


def api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    hint: str | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=structured_error(code, message, hint=hint, retryable=retryable, details=details),
    )


def is_structured_error_payload(value: Any) -> bool:
    return isinstance(value, dict) and ERROR_PAYLOAD_KEYS.issubset(value.keys())


def max_base64_chars(decoded_limit_bytes: int) -> int:
    return ((decoded_limit_bytes + 2) // 3) * 4


async def read_limited_upload(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise api_error(
            413,
            "oversized_upload",
            "Uploaded audio is too large.",
            hint=f"Record a shorter clip or keep audio under {max_bytes} bytes.",
            retryable=False,
            details={"max_bytes": max_bytes},
        )
    return data


def decode_limited_audio_base64(audio_base64: Any, max_bytes: int) -> bytes:
    if not isinstance(audio_base64, str):
        raise ValueError("audio_base64 must be a base64 string.")
    if len(audio_base64) > max_base64_chars(max_bytes):
        raise OverflowError("Decoded audio would exceed the configured upload limit.")
    audio = base64.b64decode(audio_base64, validate=True)
    if len(audio) > max_bytes:
        raise OverflowError("Decoded audio would exceed the configured upload limit.")
    return audio


async def transcribe_with_timeout(services: Services, audio: bytes, filename: str) -> Any:
    try:
        return await asyncio.wait_for(
            services.stt.transcribe(audio, filename=filename),
            timeout=services.config.runtime.stt_timeout_s,
        )
    except asyncio.TimeoutError as exc:
        raise api_error(
            504,
            "stt_timeout",
            "Speech transcription timed out.",
            hint="Try a shorter recording or use a smaller STT model.",
            retryable=True,
            details={"timeout_s": services.config.runtime.stt_timeout_s},
        ) from exc


async def send_ws_error(
    websocket: WebSocket,
    code: str,
    message: str,
    *,
    hint: str | None = None,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> None:
    await websocket.send_json(
        {
            "type": "error",
            **structured_error(code, message, hint=hint, retryable=retryable, details=details),
        }
    )


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
        config = apply_env_overrides(config)
        next_services = create_services(config)
        save_config(config, DEFAULT_CONFIG_PATH, create_backup=True)
        _services = next_services
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


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if is_structured_error_payload(exc.detail):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=structured_error(
            "http_error",
            str(exc.detail),
            retryable=exc.status_code >= 500,
            details={"status_code": exc.status_code},
        ),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=structured_error(
            "bad_request",
            "Request validation failed.",
            hint="Check the request body and parameter types.",
            details={"errors": jsonable_encoder(exc.errors())},
        ),
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


@app.post("/config/reset")
async def reset_config() -> dict:
    profile = probe_hardware()
    config = select_config(profile)
    services = await replace_services(config)
    return services.config.model_dump(mode="json")


@app.post("/stt/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict:
    services = await get_services()
    data = await read_limited_upload(file, services.config.runtime.audio_upload_max_bytes)
    if not data:
        raise api_error(
            400,
            "empty_audio_upload",
            "Uploaded audio was empty.",
            hint="Hold push-to-talk long enough for the browser to capture audio.",
            retryable=True,
        )
    try:
        result = await transcribe_with_timeout(services, data, file.filename or "input.webm")
    except STTUnavailableError as exc:
        raise api_error(
            503,
            "missing_stt_package",
            str(exc),
            hint="Install requirements-ml.txt or set stt.provider to mock for debug mode.",
            retryable=False,
        ) from exc
    except STTError as exc:
        raise api_error(
            502,
            "stt_transcription_failed",
            str(exc),
            hint="Check that the uploaded audio format can be decoded and that ffmpeg is installed.",
            retryable=True,
        ) from exc
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
                    audio = decode_limited_audio_base64(
                        audio_base64,
                        services.config.runtime.audio_upload_max_bytes,
                    )
                except OverflowError:
                    await send_ws_error(
                        websocket,
                        "oversized_upload",
                        "Uploaded audio is too large.",
                        hint=(
                            "Record a shorter clip or keep audio under "
                            f"{services.config.runtime.audio_upload_max_bytes} bytes."
                        ),
                        details={"max_bytes": services.config.runtime.audio_upload_max_bytes},
                    )
                    continue
                except (ValueError, binascii.Error):
                    await send_ws_error(
                        websocket,
                        "bad_websocket_payload",
                        "Invalid audio_base64 payload.",
                        hint="Send base64-encoded audio bytes in audio_base64.",
                    )
                    continue
                if not audio:
                    await send_ws_error(
                        websocket,
                        "empty_audio_upload",
                        "Uploaded audio was empty.",
                        hint="Hold push-to-talk long enough for the browser to capture audio.",
                        retryable=True,
                    )
                    continue
                await websocket.send_json({"type": "state", "state": "transcribing"})
                try:
                    result = await transcribe_with_timeout(services, audio, payload.get("filename") or "input.webm")
                except HTTPException as exc:
                    if is_structured_error_payload(exc.detail):
                        await websocket.send_json({"type": "error", **exc.detail})
                    else:
                        await send_ws_error(websocket, "stt_error", str(exc.detail), retryable=True)
                    continue
                except STTUnavailableError as exc:
                    await send_ws_error(
                        websocket,
                        "missing_stt_package",
                        str(exc),
                        hint="Install requirements-ml.txt or set stt.provider to mock for debug mode.",
                    )
                    continue
                except STTError as exc:
                    await send_ws_error(
                        websocket,
                        "stt_transcription_failed",
                        str(exc),
                        hint="Check that the uploaded audio format can be decoded and that ffmpeg is installed.",
                        retryable=True,
                    )
                    continue
                user_text = result.text
            elif event_type == "user_text":
                user_text = str(payload.get("text") or "").strip()
            else:
                await send_ws_error(
                    websocket,
                    "bad_websocket_payload",
                    f"Unknown event type: {event_type}",
                    hint="Send either user_text, user_audio, or interrupt events.",
                )
                continue

            if not user_text:
                await send_ws_error(
                    websocket,
                    "empty_conversation_text",
                    "No text to process.",
                    hint="Send non-empty transcribed or typed text.",
                    retryable=True,
                )
                continue
            async for event in services.conversation.run_turn(user_text):
                await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("Conversation websocket disconnected")


@app.post("/tts/generate")
async def tts_generate(payload: TTSGenerateRequest) -> Response:
    services = await get_services()
    try:
        result = await asyncio.wait_for(
            services.tts.generate(payload.text, voice=payload.voice, style=payload.style, speed=payload.speed),
            timeout=services.config.runtime.tts_timeout_s,
        )
    except asyncio.TimeoutError as exc:
        raise api_error(
            504,
            "tts_timeout",
            "Text-to-speech generation timed out.",
            hint="Try a shorter message or a faster TTS engine.",
            retryable=True,
            details={"timeout_s": services.config.runtime.tts_timeout_s},
        ) from exc
    except Exception as exc:
        raise api_error(
            502,
            "tts_generation_failed",
            str(exc),
            hint="Check the configured TTS engine and its dependencies.",
            retryable=True,
        ) from exc
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


def frontend_dist_dir() -> Path:
    configured = os.getenv("LOCAL_ASSISTANT_FRONTEND_DIST")
    if not configured:
        return ROOT_DIR / "frontend" / "dist"
    path = Path(configured)
    return path if path.is_absolute() else ROOT_DIR / path


def install_frontend_routes(application: FastAPI, dist: Path | None = None) -> None:
    dist = dist or frontend_dist_dir()
    index = dist / "index.html"
    if not index.exists():
        return

    resolved_dist = dist.resolve()
    assets = resolved_dist / "assets"
    if assets.exists():
        application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @application.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str) -> FileResponse:
        requested = (resolved_dist / path).resolve()
        try:
            requested.relative_to(resolved_dist)
        except ValueError:
            return FileResponse(index)
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(index)


install_frontend_routes(app)


def main() -> None:
    import uvicorn

    config = load_config(DEFAULT_CONFIG_PATH)
    uvicorn.run("local_assistant.server:app", host=config.server.host, port=config.server.port, reload=False)


if __name__ == "__main__":
    main()
