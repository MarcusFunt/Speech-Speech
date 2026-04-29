from local_assistant.stt.base import STTAdapter, TranscriptionResult
from local_assistant.stt.faster_whisper_adapter import FasterWhisperSTTAdapter
from local_assistant.stt.mock import MockSTTAdapter

__all__ = ["STTAdapter", "TranscriptionResult", "FasterWhisperSTTAdapter", "MockSTTAdapter"]
