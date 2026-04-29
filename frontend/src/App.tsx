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
  const [newMemory, setNewMemory] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const keyDownRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioQueueRef = useRef<string[]>([]);
  const playingRef = useRef(false);

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

  const stopPlayback = useCallback(async () => {
    audioQueueRef.current.forEach((url) => URL.revokeObjectURL(url));
    audioQueueRef.current = [];
    playingRef.current = false;
    const audio = currentAudioRef.current;
    if (audio) {
      audio.pause();
      URL.revokeObjectURL(audio.src);
      currentAudioRef.current = null;
    }
    await interruptBackend().catch(() => undefined);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "interrupt" }));
    }
  }, []);

  const playNext = useCallback(() => {
    if (playingRef.current) return;
    const nextUrl = audioQueueRef.current.shift();
    if (!nextUrl) return;
    const audio = new Audio(nextUrl);
    currentAudioRef.current = audio;
    playingRef.current = true;
    audio.onended = () => {
      URL.revokeObjectURL(nextUrl);
      playingRef.current = false;
      currentAudioRef.current = null;
      playNext();
    };
    audio.onerror = () => {
      URL.revokeObjectURL(nextUrl);
      playingRef.current = false;
      currentAudioRef.current = null;
      playNext();
    };
    void audio.play().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const enqueueAudio = useCallback(
    (base64: string, mediaType?: string) => {
      const url = decodeAudio(base64, mediaType);
      audioQueueRef.current.push(url);
      playNext();
    },
    [playNext]
  );

  const handleServerEvent = useCallback(
    (event: ServerEvent) => {
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
        if (typeof event.time_to_first_audio_ms === "number") {
          setLastAudioMs(event.time_to_first_audio_ms);
        }
        void getMemory().then(setMemory).catch(() => undefined);
      }
      if (event.type === "interrupted") {
        setAssistantDraft("");
        setState("idle");
      }
      if (event.type === "error") {
        setError(event.message ?? "Unknown backend error");
        setState("idle");
      }
    },
    [appendTranscript, enqueueAudio]
  );

  const connectWebSocket = useCallback(() => {
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
        window.setTimeout(connectWebSocket, 1000);
      }
    };
  }, [handleServerEvent]);

  useEffect(() => {
    void loadAll();
    connectWebSocket();
    return () => {
      wsRef.current?.close();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, [connectWebSocket, loadAll]);

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
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    chunksRef.current = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const recorder = new MediaRecorder(stream, { mimeType });
    mediaRecorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      setIsRecording(false);
      const blob = new Blob(chunksRef.current, { type: mimeType });
      chunksRef.current = [];
      if (blob.size === 0) {
        setState("idle");
        return;
      }
      setState("transcribing");
      try {
        const result = await transcribe(blob);
        appendTranscript("user", result.text);
        setState("thinking");
        await sendUserText(result.text);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setState("idle");
      }
    };
    recorder.start();
    setAssistantDraft("");
    setIsRecording(true);
    setState("listening");
  }, [appendTranscript, isRecording, sendUserText, stopPlayback]);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
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
    const saved = await saveConfig(config);
    setConfig(saved);
    const nextHealth = await getHealth();
    setHealth(nextHealth);
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

  return (
    <main className="app-shell">
      <section className="voice-stage">
        <header className="topbar">
          <div>
            <h1>Speech-Speech</h1>
            <div className="subline">
              <span>{statusText}</span>
              <span>{health?.tts?.active ? `Voice: ${health.tts.active}` : "Voice: loading"}</span>
              {lastAudioMs !== null && <span>{lastAudioMs} ms first audio</span>}
            </div>
          </div>
          <button className="icon-button" onClick={() => void loadAll()} title="Refresh status">
            <RefreshCw size={18} />
          </button>
        </header>

        <div className={`talk-surface ${state}`}>
          <div className="waveform" aria-hidden="true">
            {Array.from({ length: 24 }).map((_, index) => (
              <span key={index} style={{ animationDelay: `${index * 33}ms` }} />
            ))}
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
              <dd>{String(hardware?.gpu_backend ?? config?.hardware_profile?.gpu_backend ?? "unknown")}</dd>
            </div>
            <div>
              <dt>RAM</dt>
              <dd>{String(hardware?.ram_gb ?? config?.hardware_profile?.ram_gb ?? "unknown")} GB</dd>
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
