# Speech-Speech TODO

Last refreshed: 2026-04-29.

This roadmap tracks the remaining work to turn the current local voice assistant prototype into a finished v1 local web app. The repo already has a working FastAPI backend, React/Vite frontend, push-to-talk capture, local STT/LLM/TTS adapters, memory storage, hardware probing, config editing, Docker packaging work, and backend tests. The remaining work is mostly about making the voice loop reliable, making failure states understandable, and shipping a repeatable runtime.

## How to Use This TODO

- `P0` means it blocks a credible v1 demo or can corrupt user state.
- `P1` means it is needed for a polished v1.
- `P2` means it can ship after v1 if documented as a limitation.
- A task is done only when the code path, UI behavior, tests, and docs agree.
- Keep new items concrete. Prefer "add upload size limit and test 413 response" over "improve uploads".

## V1 Definition of Done

- A non-developer can install, launch, use, stop, update, and troubleshoot the app on Windows 10/11.
- The default local voice loop works end to end with real microphone input, local transcription, local LLM response, local TTS playback, and interruption.
- Optional local ML dependency failures are visible in the UI with exact missing tools/packages and one next action.
- Settings changes are validated, persisted, backed up, and recoverable.
- The frontend handles connection, microphone, model, memory, and audio states without requiring terminal logs.
- Tests cover backend contracts, frontend voice controls, interruption, config changes, memory editing, and mock-mode end-to-end flows.
- Release docs, installer behavior, Docker behavior, and runtime behavior agree with each other.

## Current Snapshot

### Verified or Implemented

- [x] FastAPI backend exposes health, hardware, config, STT, conversation, TTS, interrupt, and memory endpoints.
- [x] React/Vite frontend records push-to-talk audio and sends it through HTTP `/stt/transcribe`, then sends text over `WS /conversation/stream`.
- [x] Backend websocket can also accept `user_audio`, although this is not the primary frontend path today.
- [x] Conversation events include backend `turn_id` values.
- [x] Memory profile, episodic memory, and recent turn storage exist.
- [x] Hardware probing and config auto-selection exist.
- [x] `install.py` exposes validation flags and has smoke tests for help/debug install paths.
- [x] README documents the Python support matrix and Windows-first v1 runtime scope.
- [x] Config saves create backups, config reset re-runs auto-selection, and service replacement validates before saving.
- [x] FastAPI serves the built frontend from `frontend/dist` when present, with SPA fallback coverage.
- [x] README links to this detailed TODO.
- [x] Docker packaging exists in the working tree with frontend build, FastAPI serving, runtime volumes, and a container health check.

### Partial and Risky

- [ ] Frontend receives `turn_id` values but does not yet ignore stale events from interrupted or previous turns.
- [ ] Playback cleanup exists, but the UI does not distinguish backend generation from browser queue playback.
- [ ] Interruption calls both frontend cleanup and backend interrupt, but late-event and late-audio behavior is not tested.
- [ ] Microphone capture works on the happy path, but permission denial, missing devices, input device selection, and input level feedback are incomplete.
- [ ] Settings UI covers only a small subset of config and has no dirty-state or validation model.
- [ ] Memory UI is useful for early testing but still saves profile edits on blur and lacks search, tags editing, export/import, and recent-turn review.
- [ ] LLM fallback to mock keeps demos alive but can hide a broken local model path unless the UI marks degraded behavior clearly.
- [ ] Frontend has a build script but no unit/component/browser tests.
- [ ] Docker is usable as a packaging path, but it still needs smoke tests, volume safety checks, and clearer host Ollama troubleshooting.

## P0 - Stabilize the Voice Loop

### Frontend Turn Ownership

- [ ] Track the active backend `turn_id` in frontend state.
- [ ] Ignore `state`, `text_delta`, `audio_chunk`, `transcript`, `done`, and `error` events from non-active turns.
- [ ] Do not let an old `state: idle` event reset a newer turn.
- [ ] Clear assistant draft and queued audio only for the turn being interrupted.
- [ ] Add tests for stale event ordering, interrupt during TTS, and reconnect during a turn.

Acceptance: an interrupted turn cannot append text, enqueue audio, or reset state after a newer turn starts.

### Interruption and Playback Contract

- [ ] Define the contract for pressing push-to-talk while audio is playing.
- [ ] Cancel queued browser audio, current browser audio, backend turn generation, and in-flight TTS work.
- [ ] Revoke object URLs in every cleanup path, including component unmount.
- [ ] Add a queue length limit and drop policy for late audio.
- [ ] Surface playback errors without leaving the app stuck in `speaking`.
- [ ] Distinguish backend `speaking` from browser `playing` in state or diagnostics.

Acceptance: repeated interrupt/start cycles do not leak object URLs, replay stale audio, or leave the UI stuck.

### Microphone Capture Hardening

- [ ] Detect missing `navigator.mediaDevices` and missing audio input devices.
- [ ] Handle permission denial with an actionable frontend message.
- [ ] Add input device selection.
- [ ] Add frontend recording duration limits.
- [ ] Treat empty or tiny audio blobs as a local validation error before calling STT.
- [ ] Add real input-level feedback instead of purely animated waveform bars.

Acceptance: denied microphone access, no microphone, and empty recording all produce clear UI states and no backend turn.

### Primary Audio Path Decision

- [ ] Keep HTTP `/stt/transcribe` followed by websocket `user_text` as the v1 product path unless streaming microphone audio becomes a v1 requirement.
- [ ] Either remove websocket `user_audio` from the public API docs or mark it as backend-only experimental.
- [ ] Ensure tests cover the supported product path first.

Acceptance: README, TODO, tests, and frontend code describe one primary browser audio path.

### Latency and Diagnostics

- [ ] Track time to first transcript.
- [ ] Track time to first token.
- [x] Track time to first audio on backend conversation events.
- [ ] Track total turn time.
- [ ] Show latency as diagnostic detail, not primary UI noise.
- [ ] Add per-turn diagnostic data so interrupted and stale turns can be debugged.

Acceptance: a completed turn has enough timing data to identify whether STT, LLM, TTS, or browser playback caused user-visible delay.

## P0 - Make Failures Understandable

### Connection State

- [ ] Add explicit frontend states for connecting, connected, reconnecting, offline, backend degraded, and backend incompatible.
- [ ] Back off websocket reconnect attempts.
- [ ] Avoid creating multiple live websocket connections after reconnects.
- [ ] Display health/config load failures in a persistent banner.

Acceptance: stopping the backend and restarting it produces predictable reconnect UI without duplicate events.

### Structured Backend Errors

- [x] Standardize API and websocket errors as `{code, message, hint, retryable, details}`.
- [x] Use stable codes for missing STT package, failed STT decode, bad websocket payload, oversized upload, and STT/TTS timeout.
- [ ] Extend stable codes to unavailable LLM, missing TTS package, bad config, and remaining runtime failures.
- [ ] Map error codes to frontend messages and setup actions.

Acceptance: frontend code does not need to parse raw exception strings for common failures.

### Upload Limits and Timeouts

- [x] Add audio upload size limits for `/stt/transcribe` and websocket `user_audio`.
- [x] Add timeouts around STT, LLM, TTS, and external endpoint TTS calls.
- [x] Return structured timeout errors.
- [x] Add tests for empty upload, oversized upload, malformed websocket payload, and timeout handling.

Acceptance: bad or huge audio input cannot exhaust memory or leave the app waiting forever.

### Dependency and Setup UI

- [ ] Translate `/health` adapter data into setup status cards.
- [ ] Show missing `ffmpeg`, `espeak-ng`, `faster-whisper`, `kokoro`, Chatterbox, and Ollama model states.
- [ ] Provide one next action per missing dependency.
- [ ] Clearly mark mock fallback/degraded mode when local providers fail.

Acceptance: a user can tell from the browser why real STT, LLM, or TTS is not running.

## P1 - Complete Runtime Integrations

### STT: faster-whisper

- [ ] Validate model names and compute types before service startup.
- [ ] Detect and report missing `ffmpeg`.
- [ ] Add optional language selection in the UI.
- [ ] Add optional VAD configuration only if it improves real recordings.
- [ ] Cache model load status and expose loading/progress state.
- [ ] Add tests for unavailable package, bad model, decode failure, empty transcript, and configured language.

### LLM: Local Provider Management

- [ ] Detect whether Ollama is installed and reachable.
- [ ] Detect whether the configured model is pulled.
- [ ] Decide whether model pull/switch is UI-supported in v1 or CLI-only.
- [ ] Add provider settings for OpenAI-compatible local endpoints.
- [ ] Avoid silent mock fallback in normal mode unless the UI clearly marks degraded mode.
- [ ] Add tests for unreachable endpoint, missing model, timeout, and fallback visibility.

### TTS: Default Engine Path

- [ ] Validate Chatterbox package, `soundfile`, Kokoro fallback package, `espeak-ng`, voice names, language code, and output format.
- [ ] Add supported voice list per engine.
- [ ] Add voice preview in the UI.
- [ ] Validate speed/style ranges before saving config.
- [ ] Show fallback engine usage in transcript details or diagnostics.
- [ ] Add tests for package missing, voice missing, generation failure, and fallback selection.

### TTS: Chatterbox Voice Cloning

- [ ] Add voice sample upload.
- [ ] Store voice samples under a managed app data directory.
- [ ] Validate reference audio format and duration.
- [ ] Add UI controls for variant, language, temperature, top-p, and voice prompt path.
- [ ] Add tests for missing variant package, invalid voice path, multilingual language selection, and generation kwargs.

### TTS: Dia/Dia2 and Orpheus

- [ ] Keep Dia/Dia2 and Orpheus documented as external endpoint integrations for v1, or implement native package adapters.
- [ ] Add health states that distinguish disabled, configured endpoint, missing package, and runtime failure.
- [ ] Add endpoint contract docs for request/response shape.
- [ ] Add tests using a local fake endpoint.

## P1 - Productize the Frontend

### Component Structure

- [ ] Split `frontend/src/App.tsx` into focused components:
  - Voice stage.
  - Transcript panel.
  - Voice/settings forms.
  - Hardware/status panel.
  - Memory editor.
  - Connection/error banner.
- [ ] Keep shared turn/audio state in one owner rather than duplicating it across components.

### Settings UX

- [ ] Cover STT provider, model, language, device, and compute type.
- [ ] Cover LLM provider, base URL, model, temperature, timeout, and max tokens.
- [ ] Cover TTS provider, fallback, voice, style, speed, and engine-specific fields.
- [ ] Cover conversation chunking and max recent turns if they remain user-facing.
- [ ] Track dirty settings.
- [ ] Disable save until valid changes exist.
- [ ] Show save success/failure state.
- [ ] Prevent accidental loss when switching panels.
- [ ] Keep reset and auto-select actions available and clearly separated from save.

### Memory UX

- [ ] Save profile fields intentionally instead of on every blur.
- [ ] Add edit/delete flows for profile and episodic memory records.
- [ ] Add memory kind and tag controls.
- [ ] Add memory search/filter.
- [ ] Add recent turns viewer.
- [ ] Add clear conversation history action.
- [ ] Add export/import if local persistence is a v1 promise.

### Accessibility and Responsive Layout

- [ ] Keyboard operation for all controls.
- [ ] Visible focus states.
- [ ] ARIA labels for icon-only buttons.
- [ ] Proper live regions for recording, processing, errors, and reconnect state.
- [ ] Reduced-motion behavior for waveform animation.
- [ ] Verify narrow mobile, tablet, laptop, and wide desktop layouts.
- [ ] Ensure long model names, errors, and memory text wrap cleanly.

Acceptance: the app remains usable with keyboard-only input, browser zoom, long text, and small screens.

## P1 - Packaging and Operations

### Production Launcher

- [x] Serve production frontend from FastAPI when `frontend/dist` exists.
- [ ] Add a production launch command that builds or verifies `frontend/dist`, starts backend, opens the local URL, writes logs, and shuts down cleanly.
- [ ] Validate browser refresh and deep links if routes are added.
- [ ] Keep Vite only for development.

### Docker Hardening

- [ ] Add a Docker smoke test that builds the lightweight image and checks `/health`.
- [ ] Document host Ollama behavior on Windows, macOS, and Linux.
- [ ] Verify config, memory, logs, uploaded voices, and temp audio persist in intended mounted directories.
- [ ] Ensure container defaults are safe when bound to `0.0.0.0` inside Docker but exposed only as documented.
- [ ] Add troubleshooting for slow CPU ML image builds and missing host GPU support.

### Install and Update Path

- [ ] Ensure installer can be rerun without corrupting config or memory.
- [ ] Check existing dependencies and local models before downloading.
- [ ] Leave useful logs after failed installs.
- [ ] Add update instructions for source checkout, Python dependencies, frontend dependencies, and Docker image rebuilds.
- [ ] Add smoke tests for missing npm, missing ffmpeg, missing espeak-ng, and port collision handling.

### Data, Logs, and Diagnostics

- [ ] Define app data directory rules for config, memory database, uploaded voice samples, logs, temp audio, exports, and backups.
- [ ] Add log file output under the app data directory.
- [ ] Add a diagnostic bundle command that collects sanitized config, health, versions, hardware profile, and logs.
- [ ] Add data retention rules and user-controlled deletion.
- [ ] Add SQLite schema migration/version tracking.
- [ ] Add config schema migration support.

## P1 - Testing

### Backend Tests

- [ ] Config load/save validation and recovery.
- [ ] Hardware profile to config selection.
- [x] Mock STT transcription.
- [x] Real STT unavailable returns service error.
- [ ] STT failed-transcription cases.
- [ ] LLM provider fallback behavior and degraded-mode reporting.
- [ ] TTS primary/fallback behavior.
- [ ] Interruption behavior.
- [x] Memory CRUD basics.
- [ ] Memory search and turn history.
- [x] Static frontend route serving.
- [ ] Structured error contracts.
- [ ] Request size limits and timeouts.

### Frontend Tests

- [ ] Add a frontend test runner.
- [ ] Voice button state transitions.
- [ ] Microphone permission denial.
- [ ] Settings validation and dirty state.
- [ ] Memory add/edit/delete.
- [ ] Error banner rendering.
- [ ] Websocket reconnect behavior.
- [ ] Turn ID stale-event filtering.
- [ ] Audio queue cleanup and interrupt behavior.

### Browser End-to-End Tests

- [ ] Launch backend and frontend in mock mode.
- [ ] Confirm health and config load.
- [ ] Send text or fake audio.
- [ ] Receive assistant transcript.
- [ ] Receive playable audio chunk.
- [ ] Interrupt playback.
- [ ] Edit memory.
- [ ] Save voice settings.
- [ ] Verify refresh loads the built app when served by FastAPI.

### Manual Real-Model Matrix

- [ ] Windows CPU-only.
- [ ] Windows NVIDIA GPU if supported.
- [ ] Python 3.11 with Chatterbox, Kokoro, and faster-whisper.
- [ ] Missing optional ML packages.
- [ ] Ollama unavailable.
- [ ] Ollama model missing.
- [ ] Browser microphone denied.
- [ ] Docker lightweight mode.
- [ ] Docker ML mode.

## P2 - Performance and Advanced Features

### Performance Targets

- [ ] Define maximum acceptable time to first transcript.
- [ ] Define maximum acceptable time to first token.
- [ ] Define maximum acceptable time to first audio.
- [ ] Define maximum acceptable interruption delay.
- [ ] Measure memory, disk, and CPU/GPU use during a real session.

### Runtime Optimization

- [ ] Lazy-load heavy adapters with clear loading state.
- [ ] Keep warm models where memory allows.
- [ ] Avoid repeated health checks that trigger expensive work.
- [ ] Tune `min_chars`, `max_chars`, and `low_latency_chars` against real TTS engines.
- [ ] Avoid cutting sentences unnaturally.
- [ ] Add backpressure if TTS generation outruns playback.
- [ ] Cap transcript size and avoid storing large audio data in React state.

### Optional Advanced Voice and Memory

- [ ] Chatterbox voice cloning UI.
- [ ] Native Dia/Dia2 package adapter if still desired.
- [ ] Native Orpheus package adapter if still desired.
- [ ] Session summarization.
- [ ] Better memory retrieval and ranking.
- [ ] Input device calibration.
- [ ] Optional VAD for convenience, not as the main turn boundary.

## Documentation

- [ ] Add a user guide:
  - Install.
  - Start.
  - Choose microphone.
  - Talk.
  - Interrupt.
  - Edit voice.
  - Edit memory.
  - Troubleshoot.
- [ ] Add a developer guide:
  - Backend setup.
  - Frontend setup.
  - Test commands.
  - Mock mode.
  - Adapter development.
  - Config schema.
  - Docker development.
- [ ] Add troubleshooting pages for common failures:
  - Python version mismatch.
  - Missing npm.
  - Missing ffmpeg.
  - Missing espeak-ng.
  - faster-whisper not installed.
  - Kokoro not installed.
  - Ollama unreachable.
  - Ollama model not pulled.
  - Browser microphone blocked.
  - CORS or port collision.
  - Docker host Ollama connection.
- [ ] Add release notes and changelog.
- [ ] Add screenshots or short demo media after the UI is stable.

## Release Checklist

- [ ] All backend tests pass.
- [ ] Frontend typecheck and build pass.
- [ ] Browser end-to-end smoke test passes in mock mode.
- [ ] Installer smoke test passes on a clean machine or clean VM.
- [ ] Docker lightweight image builds and serves `/health`.
- [ ] Real local voice loop has been manually tested.
- [ ] Interrupt has been manually tested during TTS playback.
- [ ] Settings save, reset, and recovery have been tested.
- [ ] Memory add/edit/delete/export has been tested.
- [ ] Logs and diagnostics are available.
- [ ] README Quick Start is verified from scratch.
- [ ] Known limitations are documented.
