# Speech-Speech

A fully local voice-to-voice assistant prototype focused on natural spoken interaction: push-to-talk input, local transcription, local LLM responses, local TTS playback, editable memory/personality, and immediate interruption.

## Quick Start

For real local speech on Windows, use Python 3.11. Kokoro currently publishes the needed wheels for Python 3.10-3.12, not Python 3.13.

```powershell
winget install -e --id Python.Python.3.11
winget install -e --id Gyan.FFmpeg
winget install -e --id eSpeak-NG.eSpeak-NG
py -3.11 install.py
.venv\Scripts\python -m local_assistant.dev
```

Open the frontend URL printed by the dev launcher.

The installer creates `.venv`, installs backend and frontend dependencies, scans hardware, writes `config.yaml`, checks local tools, and uses Ollama as the default local LLM runtime. It attempts to install Kokoro and faster-whisper, then reports unavailable optional ML packages through the health endpoint.

If you only want mock/debug mode on Python 3.13, run:

```powershell
python install.py --skip-ml
```

## Local Runtime Defaults

- Backend: Python FastAPI.
- Frontend: React + Vite + TypeScript.
- STT: faster-whisper for real transcription, explicit mock provider for debug/test mode.
- LLM: local OpenAI-compatible endpoint first, Ollama default, mock fallback.
- TTS: Chatterbox when configured and available, Kokoro fallback, mock debug fallback.
- Memory: SQLite in `data/memory.sqlite3`.

No cloud API keys are used. Runtime calls stay local.

## Hardware Selection

`local_assistant/hardware_probe.py` detects OS, CPU, RAM, Python, NVIDIA/CUDA, AMD/ROCm, Apple Silicon/MPS, torch GPU visibility, ffmpeg, and espeak. `local_assistant/model_selector.py` converts that profile into `config.yaml`.

Policy:

- CPU or unknown GPU: Kokoro, faster-whisper tiny/base CPU int8, small Ollama model.
- CUDA 6-8 GB: Chatterbox primary, Kokoro fallback, faster-whisper base/small, 4B-8B LLM.
- CUDA 12+ GB: Chatterbox primary, Dia/Orpheus optional experimental, Kokoro fallback, 8B-14B LLM.
- Apple Silicon: MPS-compatible path where available, Kokoro fallback.

## Backend API

- `GET /health`
- `GET /hardware`
- `GET /config`
- `POST /config`
- `POST /config/autoselect`
- `POST /stt/transcribe`
- `POST /conversation/message`
- `WS /conversation/stream`
- `POST /tts/generate`
- `POST /audio/interrupt`
- `GET /memory`
- `POST /memory`
- `DELETE /memory/{id}`

## TTS Engines

Kokoro is implemented through the official `kokoro` Python package when installed:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install "kokoro>=0.9.4" soundfile "misaki[en]>=0.9.4"
```

Kokoro also needs `espeak-ng` available on PATH for best reliability. The app also expects `ffmpeg` on PATH for local audio tooling:

```powershell
winget install -e --id Gyan.FFmpeg
winget install -e --id eSpeak-NG.eSpeak-NG
```

Chatterbox is implemented through `chatterbox-tts` when installed and enabled in `config.yaml`. The install script only tries it with `--with-chatterbox` because it is more sensitive to Python and hardware. The adapter supports Turbo, original English, multilingual, local checkpoint directories, and voice-prompt paths:

```yaml
tts:
  primary: chatterbox
  fallback: kokoro
  engines:
    chatterbox:
      enabled: true
      model: chatterbox-turbo
      device: cuda
      extra:
        variant: turbo
        voices:
          clone: data/voices/reference.wav
        temperature: 0.8
        top_p: 0.95
```

Use `variant: standard` for the original English model or `variant: multilingual` with `language_id: fr`, `language_id: da`, and other Chatterbox language codes.

Dia/Dia2 and Orpheus are present as optional adapters. For v1, configure their `endpoint_url` in `config.yaml` to point at a local server that returns audio bytes.

## Development

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
pytest
cd frontend
npm install
npm run build
```

Backend:

```powershell
python -m local_assistant.server
```

The backend adds any comma-separated origins in `LOCAL_ASSISTANT_CORS_ORIGINS` to the configured CORS allow-list. This is used by the dev launcher when the frontend has to move off port 5173.

Mock STT is available only when configured explicitly:

```yaml
stt:
  provider: mock
  mock_transcript: debug transcript
  mock_language: en
```

If `stt.provider` is `faster_whisper` and the package is unavailable, `/stt/transcribe` returns `503` instead of inventing a transcript.

Frontend:

```powershell
cd frontend
npm run dev
```

Recommended combined dev startup:

```powershell
.venv\Scripts\python -m local_assistant.dev
```

`local_assistant.dev` finds free ports starting at backend `8000` and frontend `5173`, starts both processes, and sets `VITE_API_BASE` so the frontend targets the selected backend port.

## Notes

- Push-to-talk is the main turn boundary. VAD is not used to end turns.
- Pressing push-to-talk while audio is playing stops frontend playback and sends `/audio/interrupt`.
- The LLM prompt is written for speech: short sentences, no markdown by default, natural pacing, and no fake enthusiasm.
- If Ollama is unreachable, the backend returns a local mock response so the voice loop remains testable.

## TODO

- Add native Dia/Dia2 package integration beyond local endpoint support.
- Add native Orpheus package integration beyond local endpoint support.
- Add optional llama.cpp server management.
- Add voice sample upload and Chatterbox voice cloning controls.
- Add session summarization for long conversations.
- Add Playwright browser tests for push-to-talk and interruption.
