from __future__ import annotations

import re
from dataclasses import dataclass


BOUNDARY_RE = re.compile(r"([.!?;:]\s+|\n+)")
SOFT_BOUNDARY_RE = re.compile(r"(,\s+|\s+-\s+)")


@dataclass
class ChunkerSettings:
    min_chars: int = 55
    max_chars: int = 220
    low_latency_chars: int = 95


class SpeechChunker:
    def __init__(self, min_chars: int = 55, max_chars: int = 220, low_latency_chars: int = 95):
        self.settings = ChunkerSettings(min_chars, max_chars, low_latency_chars)
        self.buffer = ""

    def feed(self, text_delta: str) -> list[str]:
        self.buffer += text_delta
        chunks: list[str] = []
        while True:
            chunk = self._next_chunk()
            if not chunk:
                break
            chunks.append(chunk)
        return chunks

    def flush(self) -> list[str]:
        text = self.buffer.strip()
        self.buffer = ""
        return [text] if text else []

    def _next_chunk(self) -> str | None:
        text = self.buffer
        stripped = text.strip()
        if len(stripped) < self.settings.min_chars:
            return None

        hard = self._last_boundary(BOUNDARY_RE, text, self.settings.low_latency_chars)
        if hard is not None:
            return self._consume(hard)

        if len(stripped) >= self.settings.max_chars:
            soft = self._last_boundary(SOFT_BOUNDARY_RE, text, self.settings.min_chars)
            if soft is not None:
                return self._consume(soft)
            return self._consume(self.settings.max_chars)
        return None

    def _last_boundary(self, pattern: re.Pattern[str], text: str, min_end: int) -> int | None:
        candidates = [match.end() for match in pattern.finditer(text) if match.end() >= min_end]
        return candidates[-1] if candidates else None

    def _consume(self, end: int) -> str:
        chunk = self.buffer[:end].strip()
        self.buffer = self.buffer[end:].lstrip()
        return chunk
