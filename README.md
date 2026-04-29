# Speech-Speech

A fully local voice-to-voice assistant prototype focused on natural spoken interaction: push-to-talk input, local transcription, local LLM responses, local TTS playback, editable memory/personality, and immediate interruption.

## Quick Start

```powershell
python install.py
.venv\Scripts\python -m local_assistant.server
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173`.

The installer creates `.venv`, installs backend and frontend dependencies, scans hardware, writes `config.yaml`, checks local tools, and uses Ollama as the default local LLM runtime. It attempts to install Kokoro and faster-whisper, then falls back gracefully if optional ML packages are unavailable.

## Local Runtime Defaults

- Backend: Python FastAPI.
- Frontend: React + Vite + TypeScript.
- STT: faster-whisper first, mock fallback.
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
.venv\Scripts\python -m pip install "kokoro>=0.9.4" soundfile "misaki[en]>=0.9.4"
```

Kokoro also needs `espeak-ng` available on PATH for best reliability.

Chatterbox is implemented through `chatterbox-tts` when installed and enabled in `config.yaml`. The install script only tries it with `--with-chatterbox` because it is more sensitive to Python and hardware.

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

Frontend:

```powershell
cd frontend
npm run dev
```

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
