# Speech-Speech Web App TODO

This TODO describes what it will take to move the current prototype into a finished local web app. The current state is already a working foundation: FastAPI backend, React/Vite frontend, push-to-talk UI, local STT/LLM/TTS adapters, memory storage, hardware probing, config editing, and backend tests. The remaining work is mostly about reliability, complete user flows, runtime packaging, observability, and release quality.

## Definition of Done

A finished v1 should meet these criteria:

- A non-developer can install, launch, use, stop, update, and troubleshoot the app on the supported operating systems.
- The default local voice loop works end to end with real microphone input, local transcription, local LLM response, local TTS playback, and interruption.
- If optional local ML dependencies are missing, the app explains exactly what is missing and how to fix it.
- The frontend handles connection, microphone, model, memory, and audio states clearly without needing terminal logs.
- Settings changes are validated, persisted, and recoverable.
- Tests cover backend contracts, frontend voice controls, interruption, config changes, memory editing, and mock-mode end-to-end flows.
- Release docs, installer behavior, and runtime behavior agree with each other.

## Current Stage

- Backend API exists in `local_assistant/server.py`.
- Conversation streaming exists over `WS /conversation/stream`.
- Push-to-talk frontend exists in `frontend/src/App.tsx`.
- The frontend currently records audio, posts it to `/stt/transcribe`, then sends the transcript to the websocket as text.
- Backend has memory, prompt construction, text chunking, LLM streaming, TTS chunk generation, and interruption hooks.
- Hardware probing and config auto-selection exist.
- Mock adapters make the app testable without local ML packages.
- README documents install, dev startup, API endpoints, and some known future work.
- Backend tests exist under `tests/`.
- Frontend build script exists, but there are no frontend unit or browser tests yet.

## Phase 0 - Fix Immediate Blockers

- [x] Fix `install.py` before relying on the documented Quick Start.
  - Current issue: `args.skip_checks` and `args.skip_frontend_checks` are referenced but never added to the parser.
  - Current issue: `run_validation(...)` is referenced but not defined.
  - Decide whether installer validation should exist now or be removed until implemented.
  - Add tests or a smoke check that `python install.py --help` and at least `python install.py --skip-ml --skip-model-download` do not crash before doing useful work.
- [x] Decide the supported Python matrix for v1.
  - README recommends Python 3.11 for real local speech.
  - `pyproject.toml` allows Python 3.10 through 3.13.
  - Installer allows debug mode on newer Python but blocks local ML packages on Python 3.13.
  - Document this as a support table instead of scattering it across install notes.
- [x] Decide whether v1 supports Windows only or Windows plus macOS/Linux.
  - The current Quick Start is Windows-oriented.
  - If macOS/Linux are supported, add install commands and validate dependencies there.
- [x] Make `config.yaml` recovery safe.
  - Add backup-on-save for config changes.
  - Add reset-to-autoselected-config action.
  - Validate config before replacing live services.

## Phase 1 - Stabilize the Voice Loop

- [ ] Pick one primary audio-to-conversation path.
  - Option A: keep the current frontend flow: HTTP `/stt/transcribe` followed by websocket `user_text`.
  - Option B: send browser audio directly to websocket `user_audio`.
  - Remove or clearly mark the secondary path to reduce duplicate behavior and test surface.
- [ ] Harden microphone capture.
  - Detect unavailable microphone devices.
  - Handle browser permission denial with actionable UI.
  - Add input device selection.
  - Add recording duration limits and empty-audio handling in the frontend.
  - Add visual feedback based on real input level instead of only animated bars.
- [ ] Harden browser audio playback.
  - Handle autoplay restrictions.
  - Surface playback errors without leaving the app stuck in `speaking`.
  - Add queue length limits.
  - Revoke object URLs in every cleanup path.
  - Add a clear distinction between "backend is speaking" and "browser is still playing queued audio".
- [ ] Make interruption reliable.
  - Ensure pressing push-to-talk while audio is playing cancels queued browser audio, current backend turn, and any in-flight TTS work.
  - Add adapter-level stop behavior where supported.
  - Add tests proving interrupt prevents late audio chunks from being played.
- [ ] Improve latency tracking.
  - Track time to first transcript.
  - Track time to first token.
  - Track time to first audio.
  - Track total turn time.
  - Show these as diagnostic details, not primary UI noise.
- [ ] Add turn IDs to frontend state handling.
  - Ignore stale websocket events from interrupted or previous turns.
  - Avoid state resets from old `state: idle` messages.
  - Keep transcript and audio events associated with the correct turn.

## Phase 2 - Complete Runtime Integrations

- [ ] STT: make faster-whisper production-ready.
  - Validate model names and compute types before service startup.
  - Add clear error messages for missing ffmpeg or bad audio formats.
  - Add optional language selection in the UI.
  - Add optional VAD configuration only if it improves real recordings.
  - Cache model load status and expose loading/progress state.
- [ ] LLM: make local provider management usable.
  - Detect whether Ollama is installed and reachable.
  - Detect whether the configured model is pulled.
  - Add a UI action to pull or switch local models, or explicitly document this as CLI-only for v1.
  - Add provider settings for OpenAI-compatible local endpoints.
  - Avoid silent fallback to mock in normal mode unless the UI clearly marks it as degraded.
- [ ] TTS: finish the default engine path.
  - Validate Kokoro installation, espeak-ng, voice names, language code, and output format.
  - Add voice preview in the UI.
  - Add supported voice list per engine.
  - Add speed/style validation.
  - Show fallback engine usage in the transcript or diagnostics.
- [ ] TTS: finish optional Chatterbox controls.
  - Add voice sample upload.
  - Store voice samples under a managed app data directory.
  - Add validation for reference audio format and duration.
  - Add UI controls for Chatterbox variant, language, temperature, top-p, and voice prompt path where relevant.
- [ ] TTS: decide scope for Dia/Dia2 and Orpheus.
  - Current README says they are endpoint-only TODOs.
  - Either keep them documented as external endpoint integrations for v1 or implement native package adapters.
  - Add health checks that distinguish disabled, configured endpoint, missing package, and runtime failure.

## Phase 3 - Productize the Frontend

- [ ] Split `frontend/src/App.tsx` into focused components.
  - Voice stage.
  - Transcript panel.
  - Voice settings.
  - Hardware/status panel.
  - Memory editor.
  - Connection/error banner.
- [ ] Add a real connection state model.
  - Connecting.
  - Connected.
  - Reconnecting.
  - Offline.
  - Backend degraded.
  - Backend incompatible.
- [ ] Improve first-run experience.
  - Show setup status if models or tools are missing.
  - Provide one clear next action for each missing dependency.
  - Avoid requiring the user to inspect raw JSON health output.
- [ ] Complete settings UI.
  - STT provider, model, language, device, compute type.
  - LLM provider, base URL, model, temperature, timeout, max tokens.
  - TTS provider, fallback, voice, style, speed, engine-specific fields.
  - Conversation chunking and max recent turns if these remain user-facing.
  - Reset and auto-select buttons.
- [ ] Add unsaved-change handling.
  - Track dirty settings.
  - Disable save until valid changes exist.
  - Show save success/failure state.
  - Prevent accidental loss when switching panels.
- [ ] Improve memory UX.
  - Edit and delete profile fields intentionally instead of saving on every blur.
  - Add memory kind and tags.
  - Add memory search/filter.
  - Add recent turns viewer.
  - Add clear conversation history action.
  - Add export/import for memory data if local persistence is a v1 promise.
- [ ] Make the UI accessible.
  - Keyboard operation for all controls.
  - Visible focus states.
  - ARIA labels for icon-only buttons.
  - Proper live regions for recording/processing state.
  - Reduced-motion behavior for animated waveform.
- [ ] Polish responsive layout.
  - Verify the app on narrow mobile, tablet, laptop, and wide desktop.
  - Ensure controls never overlap.
  - Ensure long model names, errors, and memory text wrap cleanly.
  - Keep the primary voice control usable on touch devices.

## Phase 4 - Backend Reliability and Data Safety

- [ ] Add request size limits for audio uploads.
- [ ] Add timeouts around STT, LLM, and TTS calls.
- [ ] Add structured error codes for frontend handling.
- [ ] Add service startup diagnostics.
- [ ] Add config schema migration support.
- [ ] Add SQLite migration/version tracking.
- [ ] Add memory compaction or summarization for long-running use.
- [ ] Add a data retention policy and user-controlled deletion.
- [ ] Add log file output under the app data directory.
- [ ] Add a diagnostic bundle command that collects config, health, versions, and sanitized logs.
- [ ] Protect against malformed websocket payloads with strict request models.
- [ ] Ensure local-only defaults bind to `127.0.0.1` and do not expose the app on the network unexpectedly.

## Phase 5 - Testing

- [ ] Backend unit tests.
  - Config load/save validation and recovery.
  - Hardware profile to config selection.
  - STT unavailable and failed-transcription cases.
  - LLM provider fallback behavior.
  - TTS primary/fallback behavior.
  - Interruption behavior.
  - Memory CRUD, search, and turn history.
- [ ] Backend API contract tests.
  - `/health`
  - `/hardware`
  - `/config`
  - `/config/autoselect`
  - `/stt/transcribe`
  - `/conversation/message`
  - `/conversation/stream`
  - `/tts/generate`
  - `/audio/interrupt`
  - `/memory`
- [ ] Frontend unit/component tests.
  - Voice button state transitions.
  - Settings validation.
  - Memory add/edit/delete.
  - Error banner rendering.
  - Websocket reconnect behavior.
  - Audio queue cleanup.
- [ ] Browser end-to-end tests with mock adapters.
  - Launch app.
  - Confirm health loads.
  - Send text or fake audio.
  - Receive assistant transcript.
  - Receive playable audio chunk.
  - Interrupt playback.
  - Edit memory.
  - Save voice settings.
- [ ] Installer and launch tests.
  - `install.py --help`.
  - Debug-mode install.
  - Combined dev launcher.
  - Port collision handling.
  - Missing npm handling.
  - Missing ffmpeg/espeak handling.
- [ ] Manual real-model test matrix.
  - Windows CPU-only.
  - Windows NVIDIA GPU if supported.
  - Python 3.11 with local ML packages.
  - Missing optional ML packages.
  - Ollama unavailable.
  - Browser microphone denied.

## Phase 6 - Performance

- [ ] Define latency targets for v1.
  - Maximum acceptable time to first transcript.
  - Maximum acceptable time to first token.
  - Maximum acceptable time to first audio.
  - Maximum acceptable interruption delay.
- [ ] Optimize model loading.
  - Lazy-load heavy adapters with clear loading state.
  - Keep warm models where memory allows.
  - Avoid repeated health checks that trigger expensive work.
- [ ] Optimize TTS chunking.
  - Tune `min_chars`, `max_chars`, and `low_latency_chars` against real TTS engines.
  - Avoid cutting sentences unnaturally.
  - Add backpressure if TTS generation outruns playback.
- [ ] Optimize frontend rendering.
  - Cap transcript size.
  - Virtualize long memory or transcript lists if needed.
  - Avoid storing large audio data in React state.
- [ ] Measure memory and disk usage.
  - SQLite growth.
  - Audio cache growth.
  - Model cache assumptions.
  - Log retention.

## Phase 7 - Packaging and Distribution

- [ ] Decide final distribution format.
  - Developer repo only.
  - Local web app with one-command launcher.
  - Desktop wrapper around local web app.
  - Public hosted app, which would be a different product because the current repo is designed for local runtime.
- [ ] Serve production frontend from the backend.
  - Build `frontend/dist`.
  - Add FastAPI static file serving for the built app.
  - Keep Vite only for development.
  - Validate browser refresh and deep links if routes are added.
- [ ] Add a production launch command.
  - Starts backend.
  - Uses built frontend.
  - Opens the local URL.
  - Writes logs.
  - Shuts down cleanly.
- [ ] Make install/update repeatable.
  - Installer can be rerun without corrupting config or memory.
  - Dependencies can be upgraded intentionally.
  - Local models are checked before download.
  - Failed installs leave useful logs.
- [ ] Add app data directory rules.
  - Config.
  - Memory database.
  - Uploaded voice samples.
  - Logs.
  - Temporary audio.
  - Optional exports/backups.

## Phase 8 - Documentation

- [ ] Replace the short README TODO with this detailed roadmap or link to it.
- [ ] Add a user guide.
  - Install.
  - Start.
  - Choose microphone.
  - Talk.
  - Interrupt.
  - Edit voice.
  - Edit memory.
  - Troubleshoot.
- [ ] Add a developer guide.
  - Backend setup.
  - Frontend setup.
  - Test commands.
  - Mock mode.
  - Adapter development.
  - Config schema.
- [ ] Add troubleshooting pages for common failures.
  - Python version mismatch.
  - Missing npm.
  - Missing ffmpeg.
  - Missing espeak-ng.
  - faster-whisper not installed.
  - Kokoro not installed.
  - Ollama unreachable.
  - Model not pulled.
  - Browser microphone blocked.
  - CORS or port collision.
- [ ] Add release notes and changelog.
- [ ] Add screenshots or short demo media after the UI is stable.

## Phase 9 - Release Checklist

- [ ] All backend tests pass.
- [ ] Frontend typecheck and build pass.
- [ ] Browser end-to-end smoke test passes in mock mode.
- [ ] Installer smoke test passes on a clean machine or clean VM.
- [ ] Real local voice loop has been manually tested.
- [ ] Interrupt has been manually tested during TTS playback.
- [ ] Settings save, reset, and recovery have been tested.
- [ ] Memory add/edit/delete/export has been tested.
- [ ] Logs and diagnostics are available.
- [ ] README Quick Start is verified from scratch.
- [ ] Known limitations are documented.

## Suggested Milestones

### Milestone 1 - Reliable Developer Demo

- Fix `install.py`.
- Keep mock mode working.
- Add frontend build verification.
- Add basic Playwright smoke test.
- Make websocket reconnect and stale-event handling predictable.

### Milestone 2 - Real Local Voice MVP

- Validate faster-whisper, Ollama, and Kokoro paths.
- Add missing dependency UI.
- Add voice preview and settings validation.
- Make interruption reliable.
- Add first-run troubleshooting guidance.

### Milestone 3 - Finished Local Web App

- Serve built frontend from FastAPI.
- Add production launcher.
- Add installer/update path.
- Add diagnostics/logs.
- Complete frontend settings and memory UX.
- Finish test matrix and documentation.

### Milestone 4 - Optional Advanced Voice Features

- Chatterbox voice cloning UI.
- Native Dia/Dia2 or Orpheus integration if still desired.
- Session summarization.
- Better memory retrieval.
- Input device calibration and optional VAD.
