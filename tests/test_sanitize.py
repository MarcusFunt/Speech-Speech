from local_assistant.conversation.sanitize import sanitize_for_speech


def test_sanitize_removes_emoji_and_markdown_noise():
    assert sanitize_for_speech("**Hey** there 😊") == "Hey there"
