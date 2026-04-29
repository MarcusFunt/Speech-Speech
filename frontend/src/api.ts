import type { AppConfig, Health, MemoryPayload } from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export async function getHealth(): Promise<Health> {
  return jsonFetch<Health>("/health");
}

export async function getHardware(): Promise<Record<string, unknown>> {
  return jsonFetch<Record<string, unknown>>("/hardware");
}

export async function getConfig(): Promise<AppConfig> {
  return jsonFetch<AppConfig>("/config");
}

export async function saveConfig(config: AppConfig): Promise<AppConfig> {
  return jsonFetch<AppConfig>("/config", {
    method: "POST",
    body: JSON.stringify(config)
  });
}

export async function resetConfig(): Promise<AppConfig> {
  return jsonFetch<AppConfig>("/config/reset", {
    method: "POST"
  });
}

export async function transcribe(blob: Blob): Promise<{ text: string; backend: string }> {
  const body = new FormData();
  body.append("file", blob, "push-to-talk.webm");
  const response = await fetch(`${API_BASE}/stt/transcribe`, { method: "POST", body });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

export async function interruptBackend(): Promise<void> {
  await fetch(`${API_BASE}/audio/interrupt`, { method: "POST" });
}

export async function getMemory(): Promise<MemoryPayload> {
  return jsonFetch<MemoryPayload>("/memory");
}

export async function writeProfile(key: string, content: string): Promise<void> {
  await jsonFetch("/memory", {
    method: "POST",
    body: JSON.stringify({ kind: "profile", key, content })
  });
}

export async function addMemory(content: string, tags: string[] = []): Promise<void> {
  await jsonFetch("/memory", {
    method: "POST",
    body: JSON.stringify({ kind: "episodic", content, tags })
  });
}

export async function deleteMemory(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/memory/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await response.text());
  }
}
