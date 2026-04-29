from __future__ import annotations

import re


MARKDOWN_NOISE_RE = re.compile(r"[*_`>#]+")
BRACKETED_EMOJI_RE = re.compile(r"[:;=8][\-o\*']?[\)\]\(\[dDpP/:\}\{@\|\\]")


def _is_emoji_or_symbol(char: str) -> bool:
    code = ord(char)
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0xFE00 <= code <= 0xFE0F
    )


def sanitize_for_speech(text: str) -> str:
    text = BRACKETED_EMOJI_RE.sub("", text)
    text = MARKDOWN_NOISE_RE.sub("", text)
    text = "".join(char for char in text if not _is_emoji_or_symbol(char))
    text = re.sub(r"\s+", " ", text)
    return text.strip()
