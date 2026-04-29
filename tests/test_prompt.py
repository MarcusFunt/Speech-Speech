from local_assistant.config import AppConfig
from local_assistant.conversation.prompt import build_messages


def test_spoken_prompt_includes_style_and_avoids_markdown():
    messages = build_messages(
        config=AppConfig(),
        user_text="hello",
        profile={"assistant_name": "Mira", "speaking_style": "calm and brief"},
        relevant_memories=[{"content": "The user likes natural pacing."}],
        recent_turns=[],
        tts_supports_nonverbals=False,
    )
    system = messages[0]["content"]
    assert "Write for spoken audio" in system
    assert "Avoid markdown" in system
    assert "Do not use emojis" in system
    assert "calm and brief" in system
    assert messages[-1] == {"role": "user", "content": "hello"}
