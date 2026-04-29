from __future__ import annotations

import io
import math
import struct
import wave


def pcm_float_to_wav(samples: list[float], sample_rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for sample in samples:
            clipped = max(-1.0, min(1.0, sample))
            frames.extend(struct.pack("<h", int(clipped * 32767)))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()


def synthetic_voice_wav(text: str, sample_rate: int = 24000) -> bytes:
    """Create a short local debug WAV when no real TTS package is installed.

    This is intentionally simple and labeled as mock audio by the caller. It
    keeps the UI playback path testable without pretending to be a real voice.
    """
    words = max(1, len(text.split()))
    duration_s = min(5.0, max(0.55, words * 0.16))
    total = int(sample_rate * duration_s)
    samples: list[float] = []
    envelope_attack = int(sample_rate * 0.03)
    envelope_release = int(sample_rate * 0.08)
    for i in range(total):
        t = i / sample_rate
        freq = 180 + 55 * math.sin(t * 8.0) + 22 * math.sin(t * 19.0)
        sample = 0.18 * math.sin(2 * math.pi * freq * t)
        sample += 0.035 * math.sin(2 * math.pi * freq * 2.01 * t)
        if i < envelope_attack:
            sample *= i / max(1, envelope_attack)
        if total - i < envelope_release:
            sample *= max(0, total - i) / max(1, envelope_release)
        samples.append(sample)
    return pcm_float_to_wav(samples, sample_rate)
