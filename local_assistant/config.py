from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parents[1]


def _default_config_path() -> Path:
    configured = os.getenv("LOCAL_ASSISTANT_CONFIG")
    if not configured:
        return ROOT_DIR / "config.yaml"
    path = Path(configured)
    return path if path.is_absolute() else ROOT_DIR / path


DEFAULT_CONFIG_PATH = _default_config_path()


class STTConfig(BaseModel):
    provider: Literal["faster_whisper", "mock"] = "faster_whisper"
    model: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = None
    vad_filter: bool = False
    mock_transcript: str = "This is a configured mock transcription."
    mock_language: str | None = "en"


class LLMConfig(BaseModel):
    provider: Literal["openai_compatible", "ollama", "mock"] = "ollama"
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3:4b-instruct"
    api_key: str = "ollama"
    timeout_s: float = 90.0
    temperature: float = 0.8
    max_tokens: int = 420


class TTSEngineConfig(BaseModel):
    enabled: bool = True
    model: str | None = None
    endpoint_url: str | None = None
    device: str = "cpu"
    default_voice: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class TTSConfig(BaseModel):
    primary: str = "kokoro"
    fallback: str = "kokoro"
    voice: str = "af_heart"
    style: str = "natural"
    speed: float = 1.0
    engines: dict[str, TTSEngineConfig] = Field(
        default_factory=lambda: {
            "kokoro": TTSEngineConfig(
                enabled=True,
                model="Kokoro-82M",
                device="cpu",
                default_voice="af_heart",
                extra={"lang_code": "a"},
            ),
            "chatterbox": TTSEngineConfig(enabled=False, model="chatterbox-turbo", extra={"variant": "turbo"}),
            "dia": TTSEngineConfig(enabled=False),
            "orpheus": TTSEngineConfig(enabled=False),
            "mock": TTSEngineConfig(enabled=True),
        }
    )


class MemoryConfig(BaseModel):
    db_path: str = "data/memory.sqlite3"
    assistant_name: str = "Mira"
    personality: str = (
        "Warm, grounded, and direct. Respond like a thoughtful conversation partner, "
        "not a generic assistant."
    )
    speaking_style: str = (
        "Short natural spoken sentences, contractions, no markdown unless requested, "
        "mild hesitation only when it helps."
    )
    user_preferences: str = ""


class ChunkerConfig(BaseModel):
    min_chars: int = 55
    max_chars: int = 220
    low_latency_chars: int = 95


class ConversationConfig(BaseModel):
    max_recent_turns: int = 12
    allow_nonverbals: bool = False
    chunker: ChunkerConfig = Field(default_factory=ChunkerConfig)


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )


class AppConfig(BaseModel):
    version: int = 1
    data_dir: str = "data"
    audio_cache_dir: str = "data/audio"
    selected_profile: str = "low"
    hardware_profile: dict[str, Any] = Field(default_factory=dict)
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def _resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is None:
        return DEFAULT_CONFIG_PATH
    path = Path(config_path)
    return path if path.is_absolute() else ROOT_DIR / path


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def load_config(config_path: str | Path | None = None) -> AppConfig:
    path = _resolve_config_path(config_path)
    if not path.exists():
        return apply_env_overrides(AppConfig())
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return apply_env_overrides(AppConfig.model_validate(raw))


def apply_env_overrides(config: AppConfig) -> AppConfig:
    next_config = config.model_copy(deep=True)
    if value := os.getenv("LOCAL_ASSISTANT_DATA_DIR"):
        next_config.data_dir = value
    if value := os.getenv("LOCAL_ASSISTANT_AUDIO_CACHE_DIR"):
        next_config.audio_cache_dir = value
    if value := os.getenv("LOCAL_ASSISTANT_MEMORY_DB_PATH"):
        next_config.memory.db_path = value
    if value := os.getenv("LOCAL_ASSISTANT_SERVER_HOST"):
        next_config.server.host = value
    if value := os.getenv("LOCAL_ASSISTANT_SERVER_PORT"):
        next_config.server.port = int(value)
    if value := os.getenv("LOCAL_ASSISTANT_LLM_BASE_URL"):
        local_ollama_urls = {"http://localhost:11434/v1", "http://127.0.0.1:11434/v1"}
        if next_config.llm.base_url.rstrip("/") in local_ollama_urls:
            next_config.llm.base_url = value
    return next_config


def backup_config(config_path: str | Path | None = None) -> Path | None:
    path = _resolve_config_path(config_path)
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = path.with_name(f"{path.name}.{stamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def save_config(
    config: AppConfig,
    config_path: str | Path | None = None,
    *,
    create_backup: bool = False,
) -> Path:
    path = _resolve_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if create_backup:
        backup_config(path)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config.model_dump(mode="json"), handle, sort_keys=False)
    temp_path.replace(path)
    return path


def ensure_runtime_dirs(config: AppConfig) -> None:
    resolve_project_path(config.data_dir).mkdir(parents=True, exist_ok=True)
    resolve_project_path(config.audio_cache_dir).mkdir(parents=True, exist_ok=True)
    resolve_project_path(config.memory.db_path).parent.mkdir(parents=True, exist_ok=True)


def ensure_config(config_path: str | Path | None = None) -> AppConfig:
    path = _resolve_config_path(config_path)
    if path.exists():
        config = load_config(path)
    else:
        from local_assistant.hardware_probe import probe_hardware
        from local_assistant.model_selector import select_config

        config = apply_env_overrides(select_config(probe_hardware()))
        save_config(config, path)
    ensure_runtime_dirs(config)
    return config
