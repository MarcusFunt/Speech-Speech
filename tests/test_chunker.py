from local_assistant.conversation.chunker import SpeechChunker


def test_chunker_emits_sentence_boundary():
    chunker = SpeechChunker(min_chars=20, max_chars=100, low_latency_chars=30)
    chunks = chunker.feed("Okay, this is a natural sentence. Here is more")
    assert chunks == ["Okay, this is a natural sentence."]
    assert chunker.flush() == ["Here is more"]


def test_chunker_avoids_tiny_fragments():
    chunker = SpeechChunker(min_chars=40, max_chars=80, low_latency_chars=55)
    assert chunker.feed("Short. ") == []
    assert chunker.flush() == ["Short."]
