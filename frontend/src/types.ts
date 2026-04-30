export type AssistantState = "idle" | "listening" | "transcribing" | "thinking" | "speaking";

export interface AppConfig {
  selected_profile: string;
  hardware_profile: Record<string, unknown>;
  stt: {
    provider: string;
    model: string;
    device: string;
    compute_type: string;
  };
  llm: {
    provider: string;
    base_url: string;
    model: string;
    temperature: number;
  };
  tts: {
    primary: string;
    fallback: string;
    voice: string;
    style: string;
    speed: number;
    engines: Record<string, { enabled: boolean; model?: string; endpoint_url?: string; device: string }>;
  };
  memory: {
    assistant_name: string;
    personality: string;
    speaking_style: string;
    user_preferences: string;
  };
  runtime: {
    audio_upload_max_bytes: number;
    stt_timeout_s: number;
    tts_timeout_s: number;
  };
}

export interface Health {
  ok: boolean;
  profile: string;
  stt: Record<string, unknown>;
  llm: Record<string, unknown>;
  tts: {
    primary: string;
    fallback: string;
    active: string;
    adapters: Record<string, Record<string, unknown>>;
  };
}

export interface MemoryRecord {
  id: number;
  kind: string;
  content: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface MemoryPayload {
  profile: Record<string, string>;
  memories: MemoryRecord[];
  recent_turns: Array<{ id: number; role: string; content: string; created_at: string }>;
}

export interface TranscriptItem {
  id: string;
  role: "user" | "assistant";
  text: string;
}

export interface ServerEvent {
  type: string;
  state?: AssistantState;
  role?: "user" | "assistant";
  text?: string;
  delta?: string;
  code?: string;
  message?: string;
  hint?: string | null;
  retryable?: boolean;
  details?: Record<string, unknown>;
  audio_base64?: string;
  media_type?: string;
  engine?: string;
  voice?: string;
  turn_id?: string;
  time_to_first_token_ms?: number | null;
  time_to_first_audio_ms?: number | null;
  total_turn_time_ms?: number | null;
}
