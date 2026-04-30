from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import install


def test_install_help_exposes_validation_flags():
    result = subprocess.run(
        [sys.executable, "install.py", "--help"],
        cwd=install.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--skip-checks" in result.stdout
    assert "--skip-frontend-checks" in result.stdout
    assert "--torch-index-url" in result.stdout


def test_skip_ml_skip_model_download_smoke(monkeypatch, tmp_path):
    calls: list[tuple[list[str], Path, bool]] = []
    model_download_skips: list[bool] = []
    validations: list[tuple[Path, list[str] | None, bool]] = []

    def fake_run(command: list[str], *, cwd: Path = install.ROOT, check: bool = True):
        calls.append((command, cwd, check))

    def fail_optional_ml(_: Path) -> None:
        raise AssertionError("optional ML packages should be skipped")

    monkeypatch.setattr(install, "VENV", tmp_path / ".venv")
    monkeypatch.setattr(install, "run", fake_run)
    monkeypatch.setattr(install, "choose_python", lambda *, install_ml: [sys.executable])
    monkeypatch.setattr(install, "venv_python", lambda: tmp_path / ".venv-python")
    monkeypatch.setattr(install, "ensure_venv_python_supported", lambda *args, **kwargs: None)
    monkeypatch.setattr(install, "install_optional_ml", fail_optional_ml)
    monkeypatch.setattr(install, "check_system_tool", lambda *args, **kwargs: True)
    monkeypatch.setattr(install, "npm_command", lambda: None)
    monkeypatch.setattr(install, "maybe_pull_ollama_model", lambda _model, skip: model_download_skips.append(skip))
    monkeypatch.setattr(install, "maybe_install_chatterbox", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        install,
        "run_validation",
        lambda python_exe, npm, *, skip_frontend_checks=False: validations.append(
            (python_exe, npm, skip_frontend_checks)
        ),
    )
    monkeypatch.setattr(install.os, "chdir", lambda _path: None)

    install.main(["--skip-ml", "--skip-model-download"])

    assert any(command[1:3] == ["-m", "venv"] for command, _cwd, _check in calls)
    assert model_download_skips == [True]
    assert validations == [(tmp_path / ".venv-python", None, False)]


def test_default_torch_index_url_prefers_cuda_when_nvidia_is_present(monkeypatch):
    monkeypatch.setattr(install, "has_nvidia_gpu", lambda: True)
    assert install.default_torch_index_url() == install.DEFAULT_TORCH_CUDA_INDEX_URL

    monkeypatch.setattr(install, "has_nvidia_gpu", lambda: False)
    assert install.default_torch_index_url() == install.DEFAULT_TORCH_CPU_INDEX_URL
