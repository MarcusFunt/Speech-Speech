from local_assistant.memory.store import MemoryStore


def test_memory_profile_and_episodic_crud(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.set_profile("assistant_name", "Mira")
    assert store.get_profile()["assistant_name"] == "Mira"

    record = store.add_memory("episodic", "The user likes concise spoken answers.", ["style"])
    memories = store.search_memories("concise")
    assert memories[0]["id"] == record["id"]
    assert store.delete_memory(record["id"]) is True
    assert store.list_memories() == []


def test_recent_turns_are_ordered(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    store.add_turn("user", "hello")
    store.add_turn("assistant", "hey")
    assert [turn["role"] for turn in store.recent_turns()] == ["user", "assistant"]
