from __future__ import annotations

import asyncio
import importlib.util
import tempfile
from pathlib import Path

from local_assistant.config import STTConfig
from local_assistant.stt.base import (
    STTAdapter,
    STTUnavailableError,
    TranscriptionFailedError,
    TranscriptionResult,
)


class FasterWhisperSTTAdapter(STTAdapter):
    name = "faster_whisper"

    def __init__(self, config: STTConfig):
        self.config = config
        self._model = None
        self._load_error: str | None = None

    def is_available(self) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def health_check(self) -> dict:
        return {
            "name": self.name,
            "available": self.is_available(),
            "model": self.config.model,
            "device": self.config.device,
            "compute_type": self.config.compute_type,
            "load_error": self._load_error,
        }

    def _get_model(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        try:
            self._model = WhisperModel(
                self.config.model,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
        except Exception as exc:
            self._load_error = str(exc)
            raise
        return self._model

    async def transcribe(self, audio_bytes: bytes, filename: str = "input.webm") -> TranscriptionResult:
        if not self.is_available():
            raise STTUnavailableError(
                "faster-whisper is not installed. Install requirements-ml.txt or set stt.provider to mock for debug mode."
            )
        suffix = Path(filename).suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(audio_bytes)
            temp_path = Path(handle.name)
        try:
            return await asyncio.to_thread(self._transcribe_file, temp_path)
        except Exception as exc:
            self._load_error = str(exc)
            raise TranscriptionFailedError(f"faster-whisper transcription failed: {exc}") from exc
        finally:
            temp_path.unlink(missing_ok=True)

    def _transcribe_file(self, path: Path) -> TranscriptionResult:
        model = self._get_model()
        segments, info = model.transcribe(
            str(path),
            language=self.config.language,
            vad_filter=self.config.vad_filter,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            duration_s=getattr(info, "duration", None),
            backend=self.name,
        )
