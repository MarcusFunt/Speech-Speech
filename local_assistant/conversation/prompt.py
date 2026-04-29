from __future__ import annotations

from local_assistant.config import AppConfig


SPOKEN_RESPONSE_RULES = """You are a local voice conversation partner.
Write for spoken audio, not for a text chat window.
Use short, natural spoken sentences.
Avoid markdown and bullet lists unless the user explicitly asks.
Use contractions.
Sound like a real person, not a documentation page.
Do not use emojis or emoticons.
Mild hesitations like "hmm," "okay," or "yeah," are allowed, but use them rarely.
Ask short clarifying questions only when truly necessary.
Do not produce long monologues unless requested.
Match the user's energy and style.
Avoid fake constant enthusiasm.
Only use tags like [laugh], [sigh], or [chuckle] when the current TTS engine supports them, and only rarely.
"""


def build_messages(
    *,
    config: AppConfig,
    user_text: str,
    profile: dict[str, str],
    relevant_memories: list[dict],
    recent_turns: list[dict],
    tts_supports_nonverbals: bool,
) -> list[dict[str, str]]:
    assistant_name = profile.get("assistant_name") or config.memory.assistant_name
    personality = profile.get("personality") or config.memory.personality
    speaking_style = profile.get("speaking_style") or config.memory.speaking_style
    user_preferences = profile.get("user_preferences") or config.memory.user_preferences
    nonverbal_line = (
        "The selected voice can handle rare nonverbal tags."
        if tts_supports_nonverbals and config.conversation.allow_nonverbals
        else "Do not use bracketed nonverbal tags."
    )
    memory_lines = "\n".join(f"- {memory['content']}" for memory in relevant_memories[:6]) or "No relevant memory yet."
    system = f"""{SPOKEN_RESPONSE_RULES}
Assistant name: {assistant_name}
Personality: {personality}
Preferred speaking style: {speaking_style}
User preferences: {user_preferences or "None recorded yet."}
Relevant memory:
{memory_lines}
{nonverbal_line}
Keep the next answer concise and conversational."""

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for turn in recent_turns[-config.conversation.max_recent_turns :]:
        if turn["role"] in {"user", "assistant"}:
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_text})
    return messages
