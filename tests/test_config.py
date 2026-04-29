from local_assistant.config import AppConfig, load_config, save_config


def test_save_config_can_backup_existing_config(tmp_path):
    config_path = tmp_path / "config.yaml"

    save_config(AppConfig(selected_profile="low"), config_path)
    save_config(AppConfig(selected_profile="medium"), config_path, create_backup=True)

    backups = list(tmp_path.glob("config.yaml.*.bak"))
    assert len(backups) == 1
    assert load_config(backups[0]).selected_profile == "low"
    assert load_config(config_path).selected_profile == "medium"
