import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Cpu,
  Database,
  Mic,
  Pause,
  RefreshCw,
  Save,
  Settings2,
  SlidersHorizontal,
  Trash2,
  Volume2
} from "lucide-react";
import {
  API_BASE,
  WS_BASE,
  addMemory,
  deleteMemory,
  getConfig,
  getHardware,
  getHealth,
  getMemory,
  interruptBackend,
  resetConfig,
  saveConfig,
  transcribe,
  writeProfile
} from "./api";
import type { AppConfig, AssistantState, Health, MemoryPayload, ServerEvent, TranscriptItem } from "./types";

const PTT_KEYS = [
  { code: "Space", label: "Space" },
  { code: "ControlLeft", label: "Left Ctrl" },
  { code: "AltLeft", label: "Left Alt" }
];

const AUDIO_LEVEL_BARS = 24;
const MAX_AUDIO_QUEUE_LENGTH = 8;
const MAX_RECORDING_MS = 30_000;
const MIN_AUDIO_BLOB_BYTES = 512;

type BrowserPlaybackState = "idle" | "queued" | "playing" | "error";

interface TurnDiagnostics {
  timeToFirstTranscriptMs: number | null;
  timeToFirstTokenMs: number | null;
  timeToFirstAudioMs: number | null;
  totalTurnTimeMs: number | null;
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function decodeAudio(base64: string, mediaType = "audio/wav"): string {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return URL.createObjectURL(new Blob([bytes], { type: mediaType }));
}

function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || element.isContentEditable;
}

export function App() {
  const [state, setState] = useState<AssistantState>("idle");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [hardware, setHardware] = useState<Record<string, unknown> | null>(null);
  const [memory, setMemory] = useState<MemoryPayload | null>(null);
  const [transcriptItems, setTranscriptItems] = useState<TranscriptItem[]>([]);
  const [assistantDraft, setAssistantDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pttKey, setPttKey] = useState("Space");
  const [isRecording, setIsRecording] = useState(false);
  const [lastAudioMs, setLastAudioMs] = useState<number | null>(null);
  const [activeTurnId, setActiveTurnIdState] = useState<string | null>(null);
  const [browserPlayback, setBrowserPlayback] = useState<BrowserPlaybackState>("idle");
  const [queuedAudioCount, setQueuedAudioCount] = useState(0);
  const [playbackDropCount, setPlaybackDropCount] = useState(0);
  const [audioDevices, setAudioDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedAudioDeviceId, setSelectedAudioDeviceId] = useState("");
  const [inputLevel, setInputLevel] = useState(0);
  const [turnDiagnostics, setTurnDiagnostics] = useState<TurnDiagnostics>({
    timeToFirstTranscriptMs: null,
    timeToFirstTokenMs: null,
    timeToFirstAudioMs: null,
    totalTurnTimeMs: null
  });
  const [newMemory, setNewMemory] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const keyDownRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioQueueRef = useRef<string[]>([]);
  const playingRef = useRef(false);
  const activeTurnIdRef = useRef<string | null>(null);
  const ignoredTurnIdsRef = useRef<Set<string>>(new Set());
  const transcriptionStartedAtRef = useRef<number | null>(null);
  const recordingTimeoutRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const levelFrameRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const shouldReconnectRef = useRef(true);

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [nextConfig, nextHealth, nextHardware, nextMemory] = await Promise.all([
        getConfig(),
        getHealth(),
        getHardware(),
        getMemory()
      ]);
      setConfig(nextConfig);
      setHealth(nextHealth);
      setHardware(nextHardware);
      setMemory(nextMemory);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const appendTranscript = useCallback((role: "user" | "assistant", text: string) => {
    const clean = text.trim();
    if (!clean) return;
    setTranscriptItems((items) => {
      const last = items[items.length - 1];
      if (last?.role === role && last.text === clean) return items;
      return [...items, { id: makeId(), role, text: clean }].slice(-80);
    });
  }, []);

  const setActiveTurnId = useCallback((turnId: string | null) => {
    activeTurnIdRef.current = turnId;
    setActiveTurnIdState(turnId);
  }, []);

  const rememberIgnoredTurn = useCallback((turnId: string | null | undefined) => {
    if (!turnId) return;
    const ignored = ignoredTurnIdsRef.current;
    ignored.add(turnId);
    if (ignored.size > 20) {
      const [oldest] = ignored;
      ignored.delete(oldest);
    }
  }, []);

  const updateQueueCount = useCallback(() => {
    setQueuedAudioCount(audioQueueRef.current.length);
  }, []);

  const clearPlayback = useCallback(() => {
    audioQueueRef.current.forEach((url) => URL.revokeObjectURL(url));
    audioQueueRef.current = [];
    updateQueueCount();
    playingRef.current = false;
    const audio = currentAudioRef.current;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      URL.revokeObjectURL(audio.src);
      currentAudioRef.current = null;
    }
    setBrowserPlayback("idle");
  }, [updateQueueCount]);

  const stopPlayback = useCallback(async () => {
    const interruptedTurnId = activeTurnIdRef.current;
    rememberIgnoredTurn(interruptedTurnId);
    setActiveTurnId(null);
    setAssistantDraft("");
    clearPlayback();
    await interruptBackend().catch(() => undefined);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "interrupt" }));
    }
  }, [clearPlayback, rememberIgnoredTurn, setActiveTurnId]);

  const playNext = useCallback(() => {
    if (playingRef.current) return;
    const nextUrl = audioQueueRef.current.shift();
    updateQueueCount();
    if (!nextUrl) {
      setBrowserPlayback("idle");
      return;
    }
    const audio = new Audio(nextUrl);
    currentAudioRef.current = audio;
    playingRef.current = true;
    setBrowserPlayback("playing");
    let finished = false;
    const finish = (nextState: BrowserPlaybackState = "idle") => {
      if (finished) return;
      finished = true;
      URL.revokeObjectURL(nextUrl);
      playingRef.current = false;
      if (currentAudioRef.current === audio) {
        currentAudioRef.current = null;
      }
      if (audioQueueRef.current.length > 0) {
        setBrowserPlayback("queued");
        playNext();
      } else {
        setBrowserPlayback(nextState);
      }
    };
    audio.onended = () => {
      finish();
    };
    audio.onerror = () => {
      if (currentAudioRef.current !== audio) return;
      setError("Browser audio playback failed. The current chunk was skipped.");
      finish("error");
    };
    void audio.play().catch((err) => {
      if (currentAudioRef.current !== audio) return;
      setError(err instanceof Error ? err.message : String(err));
      finish("error");
    });
  }, [updateQueueCount]);

  const enqueueAudio = useCallback(
    (base64: string, mediaType?: string) => {
      const url = decodeAudio(base64, mediaType);
      if (audioQueueRef.current.length >= MAX_AUDIO_QUEUE_LENGTH) {
        URL.revokeObjectURL(url);
        setPlaybackDropCount((count) => count + 1);
        return;
      }
      audioQueueRef.current.push(url);
      updateQueueCount();
      if (!playingRef.current) {
        setBrowserPlayback("queued");
      }
      playNext();
    },
    [playNext, updateQueueCount]
  );

  const shouldHandleServerEvent = useCallback(
    (event: ServerEvent): boolean => {
      const turnId = event.turn_id;
      if (!turnId) return true;
      if (ignoredTurnIdsRef.current.has(turnId)) return false;

      const active = activeTurnIdRef.current;
      if (!active) {
        setActiveTurnId(turnId);
        return true;
      }
      return active === turnId;
    },
    [setActiveTurnId]
  );

  const updateTurnDiagnostics = useCallback((event: ServerEvent) => {
    setTurnDiagnostics((current) => ({
      timeToFirstTranscriptMs: current.timeToFirstTranscriptMs,
      timeToFirstTokenMs:
        typeof event.time_to_first_token_ms === "number" ? event.time_to_first_token_ms : current.timeToFirstTokenMs,
      timeToFirstAudioMs:
        typeof event.time_to_first_audio_ms === "number" ? event.time_to_first_audio_ms : current.timeToFirstAudioMs,
      totalTurnTimeMs: typeof event.total_turn_time_ms === "number" ? event.total_turn_time_ms : current.totalTurnTimeMs
    }));
  }, []);

  const handleServerEvent = useCallback(
    (event: ServerEvent) => {
      if (!shouldHandleServerEvent(event)) return;
      updateTurnDiagnostics(event);
      if (event.type === "state" && event.state) {
        setState(event.state);
      }
      if (event.type === "transcript" && event.role && event.text) {
        appendTranscript(event.role, event.text);
        if (event.role === "assistant") setAssistantDraft("");
      }
      if (event.type === "text_delta" && event.delta) {
        setAssistantDraft((draft) => draft + event.delta);
      }
      if (event.type === "audio_chunk" && event.audio_base64) {
        enqueueAudio(event.audio_base64, event.media_type);
        if (typeof event.time_to_first_audio_ms === "number") {
          setLastAudioMs(event.time_to_first_audio_ms);
        }
      }
      if (event.type === "done") {
        setState("idle");
        rememberIgnoredTurn(event.turn_id);
        setActiveTurnId(null);
        if (typeof event.time_to_first_audio_ms === "number") {
          setLastAudioMs(event.time_to_first_audio_ms);
        }
        void getMemory().then(setMemory).catch(() => undefined);
      }
      if (event.type === "interrupted") {
        setAssistantDraft("");
        setState("idle");
        rememberIgnoredTurn(event.turn_id);
        setActiveTurnId(null);
      }
      if (event.type === "error") {
        const message = event.message ?? "Unknown backend error";
        setError(event.hint ? `${message} ${event.hint}` : message);
        setState("idle");
        rememberIgnoredTurn(event.turn_id);
        setActiveTurnId(null);
      }
    },
    [appendTranscript, enqueueAudio, rememberIgnoredTurn, setActiveTurnId, shouldHandleServerEvent, updateTurnDiagnostics]
  );

  const connectWebSocket = useCallback(() => {
    const existing = wsRef.current;
    if (existing?.readyState === WebSocket.OPEN || existing?.readyState === WebSocket.CONNECTING) {
      return;
    }
    const ws = new WebSocket(`${WS_BASE}/conversation/stream`);
    wsRef.current = ws;
    ws.onmessage = (message) => {
      try {
        handleServerEvent(JSON.parse(message.data) as ServerEvent);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    };
    ws.onclose = () => {
      if (wsRef.current === ws) {
        wsRef.current = null;
        if (!shouldReconnectRef.current) return;
        reconnectTimerRef.current = window.setTimeout(connectWebSocket, 1000);
      }
    };
  }, [handleServerEvent]);

  const refreshAudioDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) {
      setAudioDevices([]);
      return [];
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter((device) => device.kind === "audioinput");
      setAudioDevices(inputs);
      setSelectedAudioDeviceId((selected) =>
        selected && inputs.some((device) => device.deviceId === selected) ? selected : ""
      );
      return inputs;
    } catch {
      setAudioDevices([]);
      return [];
    }
  }, []);

  const cleanupInputLevel = useCallback(() => {
    if (levelFrameRef.current !== null) {
      window.cancelAnimationFrame(levelFrameRef.current);
      levelFrameRef.current = null;
    }
    audioSourceRef.current?.disconnect();
    audioSourceRef.current = null;
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context && context.state !== "closed") {
      void context.close().catch(() => undefined);
    }
    setInputLevel(0);
  }, []);

  const startInputLevel = useCallback(
    (stream: MediaStream) => {
      cleanupInputLevel();
      const AudioContextClass =
        window.AudioContext ??
        (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextClass) return;

      let context: AudioContext;
      let source: MediaStreamAudioSourceNode;
      let analyser: AnalyserNode;
      try {
        context = new AudioContextClass();
        source = context.createMediaStreamSource(stream);
        analyser = context.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
      } catch {
        cleanupInputLevel();
        return;
      }
      audioContextRef.current = context;
      audioSourceRef.current = source;

      const samples = new Uint8Array(analyser.fftSize);
      const readLevel = () => {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) {
          const centered = sample - 128;
          sum += centered * centered;
        }
        const rms = Math.sqrt(sum / samples.length) / 128;
        setInputLevel(Math.min(1, rms * 4));
        levelFrameRef.current = window.requestAnimationFrame(readLevel);
      };
      readLevel();
    },
    [cleanupInputLevel]
  );

  const microphoneErrorMessage = useCallback((err: unknown): string => {
    if (err instanceof DOMException) {
      if (err.name === "NotAllowedError" || err.name === "SecurityError") {
        return "Microphone permission was denied. Allow microphone access in the browser and try again.";
      }
      if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
        return "No microphone was found. Connect an input device and refresh the page.";
      }
      if (err.name === "NotReadableError") {
        return "The microphone is already in use by another app. Close the other app and try again.";
      }
    }
    return err instanceof Error ? err.message : String(err);
  }, []);

  useEffect(() => {
    shouldReconnectRef.current = true;
    void loadAll();
    void refreshAudioDevices();
    connectWebSocket();
    const handleDeviceChange = () => {
      void refreshAudioDevices();
    };
    navigator.mediaDevices?.addEventListener?.("devicechange", handleDeviceChange);
    return () => {
      shouldReconnectRef.current = false;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      wsRef.current?.close();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (recordingTimeoutRef.current !== null) {
        window.clearTimeout(recordingTimeoutRef.current);
        recordingTimeoutRef.current = null;
      }
      cleanupInputLevel();
      clearPlayback();
      navigator.mediaDevices?.removeEventListener?.("devicechange", handleDeviceChange);
    };
  }, [cleanupInputLevel, clearPlayback, connectWebSocket, loadAll, refreshAudioDevices]);

  const sendUserText = useCallback(
    async (text: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "user_text", text }));
        return;
      }
      const response = await fetch(`${API_BASE}/conversation/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text })
      });
      const payload = await response.json();
      for (const event of payload.events ?? []) {
        handleServerEvent(event as ServerEvent);
      }
    },
    [handleServerEvent]
  );

  const startRecording = useCallback(async () => {
    if (isRecording) return;
    setError(null);
    await stopPlayback();
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Microphone capture is not available in this browser or context.");
      setState("idle");
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      setError("Audio recording is not supported in this browser.");
      setState("idle");
      return;
    }

    const devices = await refreshAudioDevices();
    if (devices.length === 0) {
      setError("No microphone was found. Connect an input device and refresh the page.");
      setState("idle");
      return;
    }

    let stream: MediaStream;
    try {
      const audio: MediaTrackConstraints | boolean = selectedAudioDeviceId
        ? { deviceId: { exact: selectedAudioDeviceId } }
        : true;
      stream = await navigator.mediaDevices.getUserMedia({ audio });
    } catch (err) {
      setError(microphoneErrorMessage(err));
      setState("idle");
      return;
    }

    void refreshAudioDevices();
    streamRef.current = stream;
    chunksRef.current = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const recorder = new MediaRecorder(stream, { mimeType });
    mediaRecorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = async () => {
      if (recordingTimeoutRef.current !== null) {
        window.clearTimeout(recordingTimeoutRef.current);
        recordingTimeoutRef.current = null;
      }
      cleanupInputLevel();
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      mediaRecorderRef.current = null;
      setIsRecording(false);
      const blob = new Blob(chunksRef.current, { type: mimeType });
      chunksRef.current = [];
      if (blob.size < MIN_AUDIO_BLOB_BYTES) {
        setError("Recording was too short or empty. Hold push-to-talk long enough for audio to be captured.");
        setState("idle");
        return;
      }
      setState("transcribing");
      transcriptionStartedAtRef.current = performance.now();
      try {
        const result = await transcribe(blob);
        const started = transcriptionStartedAtRef.current;
        if (started !== null) {
          setTurnDiagnostics((current) => ({
            ...current,
            timeToFirstTranscriptMs: Math.round(performance.now() - started)
          }));
        }
        appendTranscript("user", result.text);
        setState("thinking");
        await sendUserText(result.text);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setState("idle");
      } finally {
        transcriptionStartedAtRef.current = null;
      }
    };
    recorder.start();
    recordingTimeoutRef.current = window.setTimeout(() => {
      const activeRecorder = mediaRecorderRef.current;
      if (activeRecorder && activeRecorder.state !== "inactive") {
        setError(`Recording stopped after ${Math.round(MAX_RECORDING_MS / 1000)} seconds.`);
        activeRecorder.stop();
      }
    }, MAX_RECORDING_MS);
    setAssistantDraft("");
    setTurnDiagnostics({
      timeToFirstTranscriptMs: null,
      timeToFirstTokenMs: null,
      timeToFirstAudioMs: null,
      totalTurnTimeMs: null
    });
    setLastAudioMs(null);
    setPlaybackDropCount(0);
    setIsRecording(true);
    setState("listening");
    startInputLevel(stream);
  }, [
    appendTranscript,
    cleanupInputLevel,
    isRecording,
    microphoneErrorMessage,
    refreshAudioDevices,
    selectedAudioDeviceId,
    sendUserText,
    startInputLevel,
    stopPlayback
  ]);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
      return;
    }
    if (recordingTimeoutRef.current !== null) {
      window.clearTimeout(recordingTimeoutRef.current);
      recordingTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== pttKey || keyDownRef.current || isTypingTarget(event.target)) return;
      event.preventDefault();
      keyDownRef.current = true;
      void startRecording();
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code !== pttKey) return;
      event.preventDefault();
      keyDownRef.current = false;
      stopRecording();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [pttKey, startRecording, stopRecording]);

  const statusText = useMemo(() => {
    if (state === "idle") return "Idle";
    if (state === "listening") return "Listening";
    if (state === "transcribing") return "Transcribing";
    if (state === "thinking") return "Thinking";
    return "Speaking";
  }, [state]);

  async function persistVoiceSettings() {
    if (!config) return;
    try {
      setError(null);
      const saved = await saveConfig(config);
      setConfig(saved);
      const nextHealth = await getHealth();
      setHealth(nextHealth);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function resetToAutoselectedConfig() {
    try {
      setError(null);
      const nextConfig = await resetConfig();
      const [nextHealth, nextHardware] = await Promise.all([getHealth(), getHardware()]);
      setConfig(nextConfig);
      setHealth(nextHealth);
      setHardware(nextHardware);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function persistProfile(key: string, value: string) {
    await writeProfile(key, value);
    setMemory(await getMemory());
  }

  async function createMemory() {
    const clean = newMemory.trim();
    if (!clean) return;
    await addMemory(clean);
    setNewMemory("");
    setMemory(await getMemory());
  }

  async function removeMemory(id: number) {
    await deleteMemory(id);
    setMemory(await getMemory());
  }

  const gpuBackend = String(hardware?.gpu_backend ?? config?.hardware_profile?.gpu_backend ?? "unknown");
  const gpuName = String(hardware?.nvidia_name ?? config?.hardware_profile?.nvidia_name ?? "").trim();
  const gpuLabel = gpuName && gpuBackend !== "unknown" ? `${gpuBackend} (${gpuName})` : gpuName || gpuBackend;
  const ramValue = hardware?.ram_gb ?? config?.hardware_profile?.ram_gb;
  const ramLabel = ramValue === null || ramValue === undefined ? "unknown" : `${String(ramValue)} GB`;

  return (
    <main className="app-shell">
      <section className="voice-stage">
        <header className="topbar">
          <div>
            <h1>Speech-Speech</h1>
            <div className="subline">
              <span>{statusText}</span>
              <span>{health?.tts?.active ? `Voice: ${health.tts.active}` : "Voice: loading"}</span>
              {activeTurnId && <span>Turn: {activeTurnId.slice(0, 8)}</span>}
              {turnDiagnostics.timeToFirstTranscriptMs !== null && (
                <span>{turnDiagnostics.timeToFirstTranscriptMs} ms transcript</span>
              )}
              {turnDiagnostics.timeToFirstTokenMs !== null && (
                <span>{turnDiagnostics.timeToFirstTokenMs} ms first token</span>
              )}
              {(turnDiagnostics.timeToFirstAudioMs ?? lastAudioMs) !== null && (
                <span>{turnDiagnostics.timeToFirstAudioMs ?? lastAudioMs} ms first audio</span>
              )}
              {turnDiagnostics.totalTurnTimeMs !== null && <span>{turnDiagnostics.totalTurnTimeMs} ms total</span>}
              {browserPlayback !== "idle" && <span>Browser: {browserPlayback}</span>}
              {queuedAudioCount > 0 && <span>{queuedAudioCount} queued</span>}
              {playbackDropCount > 0 && <span>{playbackDropCount} audio dropped</span>}
            </div>
          </div>
          <button className="icon-button" onClick={() => void loadAll()} title="Refresh status">
            <RefreshCw size={18} />
          </button>
        </header>

        <div className={`talk-surface ${state}`}>
          <div className="waveform" aria-hidden="true">
            {Array.from({ length: AUDIO_LEVEL_BARS }).map((_, index) => {
              const level = Math.min(1, inputLevel * (0.55 + (index % 6) * 0.11));
              return (
                <span
                  key={index}
                  style={{
                    animationDelay: `${index * 33}ms`,
                    ...(isRecording
                      ? {
                          height: `${14 + level * 82}px`,
                          opacity: 0.3 + level * 0.7
                        }
                      : {})
                  }}
                />
              );
            })}
          </div>
          <button
            className="ptt-button"
            onPointerDown={() => void startRecording()}
            onPointerUp={stopRecording}
            onPointerLeave={() => {
              if (isRecording) stopRecording();
            }}
            aria-pressed={isRecording}
          >
            {isRecording ? <Pause size={42} /> : <Mic size={44} />}
            <span>{isRecording ? "Release" : "Hold"}</span>
          </button>
          <div className="key-row">
            <label>
              Keyboard
              <select value={pttKey} onChange={(event) => setPttKey(event.target.value)}>
                {PTT_KEYS.map((key) => (
                  <option value={key.code} key={key.code}>
                    {key.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Microphone
              <select
                value={selectedAudioDeviceId}
                onChange={(event) => setSelectedAudioDeviceId(event.target.value)}
                disabled={audioDevices.length === 0 || isRecording}
              >
                <option value="">Default</option>
                {audioDevices.map((device, index) => (
                  <option value={device.deviceId} key={device.deviceId || `input-${index}`}>
                    {device.label || `Input ${index + 1}`}
                  </option>
                ))}
              </select>
            </label>
            <button className="secondary-button" onClick={() => void stopPlayback()}>
              <Volume2 size={16} />
              Stop
            </button>
          </div>
        </div>

        {error && <div className="error-line">{error}</div>}

        <section className="transcript-panel">
          <div className="panel-heading">
            <Activity size={18} />
            <h2>Transcript</h2>
          </div>
          <div className="transcript-list">
            {transcriptItems.map((item) => (
              <article className={`turn ${item.role}`} key={item.id}>
                <span>{item.role}</span>
                <p>{item.text}</p>
              </article>
            ))}
            {assistantDraft && (
              <article className="turn assistant live">
                <span>assistant</span>
                <p>{assistantDraft}</p>
              </article>
            )}
          </div>
        </section>
      </section>

      <aside className="side-rail">
        <section className="panel">
          <div className="panel-heading">
            <SlidersHorizontal size={18} />
            <h2>Voice</h2>
          </div>
          {config && (
            <div className="form-grid">
              <label>
                Engine
                <select
                  value={config.tts.primary}
                  onChange={(event) =>
                    setConfig({ ...config, tts: { ...config.tts, primary: event.target.value } })
                  }
                >
                  {Object.keys(config.tts.engines).map((engine) => (
                    <option key={engine} value={engine}>
                      {engine}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Voice
                <input
                  value={config.tts.voice}
                  onChange={(event) => setConfig({ ...config, tts: { ...config.tts, voice: event.target.value } })}
                />
              </label>
              <label>
                Style
                <select
                  value={config.tts.style}
                  onChange={(event) => setConfig({ ...config, tts: { ...config.tts, style: event.target.value } })}
                >
                  <option value="natural">natural</option>
                  <option value="calm">calm</option>
                  <option value="expressive">expressive</option>
                  <option value="soft">soft</option>
                </select>
              </label>
              <label>
                Speed {config.tts.speed.toFixed(2)}
                <input
                  type="range"
                  min="0.75"
                  max="1.25"
                  step="0.05"
                  value={config.tts.speed}
                  onChange={(event) =>
                    setConfig({ ...config, tts: { ...config.tts, speed: Number(event.target.value) } })
                  }
                />
              </label>
              <button className="primary-small" onClick={() => void persistVoiceSettings()}>
                <Save size={16} />
                Save
              </button>
            </div>
          )}
          {health?.tts && <pre className="status-block">{JSON.stringify(health.tts, null, 2)}</pre>}
        </section>

        <section className="panel">
          <div className="panel-heading">
            <Cpu size={18} />
            <h2>Hardware</h2>
          </div>
          <dl className="facts">
            <div>
              <dt>Profile</dt>
              <dd>{config?.selected_profile ?? "loading"}</dd>
            </div>
            <div>
              <dt>GPU</dt>
              <dd>{gpuLabel}</dd>
            </div>
            <div>
              <dt>RAM</dt>
              <dd>{ramLabel}</dd>
            </div>
            <div>
              <dt>STT</dt>
              <dd>{config ? `${config.stt.provider} ${config.stt.model}` : "loading"}</dd>
            </div>
            <div>
              <dt>LLM</dt>
              <dd>{config ? `${config.llm.provider} ${config.llm.model}` : "loading"}</dd>
            </div>
          </dl>
          <div className="panel-actions">
            <button className="secondary-button" onClick={() => void resetToAutoselectedConfig()} title="Reset config to the auto-selected hardware profile">
              <Settings2 size={16} />
              Auto-select
            </button>
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <Database size={18} />
            <h2>Memory</h2>
          </div>
          {memory && (
            <div className="memory-editor">
              {["assistant_name", "personality", "speaking_style", "user_preferences"].map((key) => (
                <label key={key}>
                  {key.replace(/_/g, " ")}
                  <textarea
                    value={memory.profile[key] ?? ""}
                    onChange={(event) =>
                      setMemory({
                        ...memory,
                        profile: { ...memory.profile, [key]: event.target.value }
                      })
                    }
                    onBlur={(event) => void persistProfile(key, event.target.value)}
                    rows={key === "assistant_name" ? 1 : 3}
                  />
                </label>
              ))}
              <div className="memory-add">
                <textarea value={newMemory} onChange={(event) => setNewMemory(event.target.value)} rows={3} />
                <button className="primary-small" onClick={() => void createMemory()}>
                  <Save size={16} />
                  Add
                </button>
              </div>
              <div className="memory-list">
                {memory.memories.slice(0, 10).map((record) => (
                  <article className="memory-row" key={record.id}>
                    <p>{record.content}</p>
                    <button className="icon-button" onClick={() => void removeMemory(record.id)} title="Delete memory">
                      <Trash2 size={15} />
                    </button>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>
      </aside>
    </main>
  );
}
