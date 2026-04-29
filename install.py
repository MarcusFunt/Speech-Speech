from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
ML_MIN_PYTHON = (3, 10)
ML_MAX_PYTHON = (3, 13)
BASE_MAX_PYTHON = (3, 14)


def run(command: list[str], *, cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    print(f"> {' '.join(command)}")
    return subprocess.run(command, cwd=cwd, check=check)


def python_version(executable: str) -> tuple[int, int] | None:
    code = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    try:
        result = subprocess.run([executable, "-c", code], capture_output=True, text=True, check=True)
        major, minor = result.stdout.strip().split(".")
        return int(major), int(minor)
    except Exception:
        return None


def launcher_python(version: str) -> str | None:
    if platform.system().lower() != "windows" or not shutil.which("py"):
        return None
    try:
        subprocess.run(["py", f"-{version}", "-c", "import sys"], capture_output=True, check=True)
        return f"py -{version}"
    except subprocess.CalledProcessError:
        return None


def supports_ml_python(version: tuple[int, int] | None) -> bool:
    return version is not None and ML_MIN_PYTHON <= version < ML_MAX_PYTHON


def supports_base_python(version: tuple[int, int] | None) -> bool:
    return version is not None and ML_MIN_PYTHON <= version < BASE_MAX_PYTHON


def print_ml_python_error(version: tuple[int, int] | None, executable: str) -> None:
    detected = f"{version[0]}.{version[1]}" if version else "unknown"
    print(
        "\nPython 3.10, 3.11, or 3.12 is required when installing local ML packages "
        "(faster-whisper and Kokoro)."
    )
    print(f"Detected Python {detected}: {executable}")
    print("\nChoose one:")
    print("  1. Install Python 3.11, then rerun: py -3.11 install.py")
    print("  2. Keep this Python for debug mode only: python install.py --skip-ml")


def choose_python(*, install_ml: bool) -> list[str]:
    current = python_version(sys.executable)
    if supports_ml_python(current):
        return [sys.executable]
    if not install_ml and supports_base_python(current):
        if current and current >= ML_MAX_PYTHON:
            print(
                "Warning: Python 3.13 is supported only for --skip-ml debug installs. "
                "Use Python 3.11 for Kokoro/faster-whisper."
            )
        return [sys.executable]
    for version in ["3.11", "3.12", "3.10"]:
        launcher = launcher_python(version)
        if launcher:
            return launcher.split(" ")
    if install_ml:
        print_ml_python_error(current, sys.executable)
        raise SystemExit(1)
    if not supports_base_python(current):
        print("Python 3.10 through 3.13 is required for debug installs.")
        raise SystemExit(1)
    return [sys.executable]


def venv_python() -> Path:
    if platform.system().lower() == "windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def check_system_tool(name: str, install_hint: str) -> bool:
    if shutil.which(name):
        print(f"{name}: found")
        return True
    print(f"{name}: missing")
    print(f"  {install_hint}")
    return False


def npm_command() -> list[str] | None:
    for name in ["npm.cmd", "npm"]:
        path = shutil.which(name)
        if path:
            return [path]
    return None


def maybe_pull_ollama_model(model: str, skip: bool) -> None:
    if skip:
        return
    if not shutil.which("ollama"):
        print("Ollama not found. Install Ollama or configure another local OpenAI-compatible endpoint.")
        return
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False)
    if model in result.stdout:
        print(f"Ollama model already present: {model}")
        return
    print(f"Pulling local Ollama model: {model}")
    run(["ollama", "pull", model], check=False)


def maybe_install_chatterbox(python_exe: Path, enabled: bool) -> None:
    if not enabled:
        return
    version = python_version(str(python_exe))
    if version != (3, 11):
        print("Skipping Chatterbox install because Python 3.11 is required for the most reliable path.")
        return
    run([str(python_exe), "-m", "pip", "install", "chatterbox-tts"], check=False)


def ensure_venv_python_supported(python_exe: Path, *, install_ml: bool) -> None:
    version = python_version(str(python_exe))
    if install_ml and not supports_ml_python(version):
        print_ml_python_error(version, str(python_exe))
        print(
            "\nThe existing .venv uses an incompatible Python for Kokoro. "
            "Rename or remove .venv, then rerun with Python 3.11."
        )
        raise SystemExit(1)


def install_optional_ml(python_exe: Path) -> None:
    optional_groups = [
        ["faster-whisper>=1.0.0"],
        ["kokoro>=0.9.4", "soundfile", "misaki[en]>=0.9.4"],
    ]
    for packages in optional_groups:
        run([str(python_exe), "-m", "pip", "install", *packages], check=False)


def run_validation(python_exe: Path, npm: list[str] | None, *, skip_frontend_checks: bool = False) -> None:
    print("\nRunning install validation...")
    run(
        [
            str(python_exe),
            "-c",
            (
                "from local_assistant.config import load_config; "
                "from local_assistant.server import create_services; "
                "config=load_config(); create_services(config); "
                "print('Backend service validation passed')"
            ),
        ]
    )
    if skip_frontend_checks:
        print("Skipping frontend validation.")
    elif npm:
        run([*npm, "run", "build"], cwd=ROOT / "frontend")
    else:
        print("Skipping frontend validation because npm was not found.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Install the local voice-to-voice assistant.")
    parser.add_argument("--skip-ml", action="store_true", help="Skip faster-whisper and Kokoro package installation.")
    parser.add_argument("--skip-model-download", action="store_true", help="Do not pull Ollama models.")
    parser.add_argument("--with-chatterbox", action="store_true", help="Try to install Chatterbox even if hardware is not ideal.")
    parser.add_argument("--skip-checks", action="store_true", help="Skip post-install backend and frontend validation.")
    parser.add_argument("--skip-frontend-checks", action="store_true", help="Skip the frontend build validation only.")
    args = parser.parse_args(argv)

    install_ml = not args.skip_ml
    python_cmd = choose_python(install_ml=install_ml)
    if not VENV.exists():
        run([*python_cmd, "-m", "venv", str(VENV)])
    python_exe = venv_python()
    ensure_venv_python_supported(python_exe, install_ml=install_ml)

    run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python_exe), "-m", "pip", "install", "-r", "requirements.txt"])
    if install_ml:
        install_optional_ml(python_exe)

    check_system_tool("ffmpeg", "Install ffmpeg and ensure it is on PATH. Windows: winget install -e --id Gyan.FFmpeg")
    check_system_tool(
        "espeak-ng",
        "Install espeak-ng for Kokoro G2P fallback. Windows: winget install -e --id eSpeak-NG.eSpeak-NG",
    )

    npm = npm_command()
    if npm:
        run([*npm, "install"], cwd=ROOT / "frontend")
    else:
        print("npm not found. Install Node.js/npm before running the web frontend.")

    run(
        [
            str(python_exe),
            "-c",
            (
                "from local_assistant.hardware_probe import probe_hardware; "
                "from local_assistant.model_selector import select_config; "
                "from local_assistant.config import save_config; "
                "config=select_config(probe_hardware()); save_config(config, create_backup=True); "
                "print(config.model_dump_json(indent=2))"
            ),
        ]
    )

    maybe_pull_ollama_model("qwen3:4b-instruct", args.skip_model_download)
    maybe_install_chatterbox(python_exe, args.with_chatterbox)

    if not args.skip_checks:
        run_validation(python_exe, npm, skip_frontend_checks=args.skip_frontend_checks)

    backend_cmd = f"{python_exe} -m local_assistant.server"
    frontend_cmd = "cd frontend; $env:VITE_API_BASE='http://127.0.0.1:8000'; npm run dev"
    dev_cmd = f"{python_exe} -m local_assistant.dev"
    print("\nInstall complete.")
    print(f"Dev:      {dev_cmd}")
    print(f"Backend:  {backend_cmd}")
    print(f"Frontend: {frontend_cmd}")
    print("Open:     Run the Dev command and use the URL it prints.")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
