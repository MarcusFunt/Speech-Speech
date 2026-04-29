from local_assistant.config import AppConfig, LLMConfig, apply_env_overrides, load_config, save_config


def test_save_config_can_backup_existing_config(tmp_path):
    config_path = tmp_path / "config.yaml"

    save_config(AppConfig(selected_profile="low"), config_path)
    save_config(AppConfig(selected_profile="medium"), config_path, create_backup=True)

    backups = list(tmp_path.glob("config.yaml.*.bak"))
    assert len(backups) == 1
    assert load_config(backups[0]).selected_profile == "low"
    assert load_config(config_path).selected_profile == "medium"


def test_env_overrides_runtime_paths_and_server(monkeypatch):
    monkeypatch.setenv("LOCAL_ASSISTANT_DATA_DIR", "/data")
    monkeypatch.setenv("LOCAL_ASSISTANT_AUDIO_CACHE_DIR", "/data/audio")
    monkeypatch.setenv("LOCAL_ASSISTANT_MEMORY_DB_PATH", "/data/memory.sqlite3")
    monkeypatch.setenv("LOCAL_ASSISTANT_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("LOCAL_ASSISTANT_SERVER_PORT", "9000")
    monkeypatch.setenv("LOCAL_ASSISTANT_LLM_BASE_URL", "http://host.docker.internal:11434/v1")

    config = apply_env_overrides(AppConfig())

    assert config.data_dir == "/data"
    assert config.audio_cache_dir == "/data/audio"
    assert config.memory.db_path == "/data/memory.sqlite3"
    assert config.server.host == "0.0.0.0"
    assert config.server.port == 9000
    assert config.llm.base_url == "http://host.docker.internal:11434/v1"

    custom_llm_config = apply_env_overrides(
        AppConfig(llm=LLMConfig(base_url="http://llm.internal:8080/v1"))
    )
    assert custom_llm_config.llm.base_url == "http://llm.internal:8080/v1"
