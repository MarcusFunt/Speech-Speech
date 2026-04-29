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


def choose_python() -> list[str]:
    current = python_version(sys.executable)
    if current and (3, 10) <= current <= (3, 12):
        return [sys.executable]
    for version in ["3.11", "3.12", "3.10"]:
        launcher = launcher_python(version)
        if launcher:
            return launcher.split(" ")
    print(
        "Warning: Python 3.11 is preferred for local ML packages. "
        f"Continuing with {sys.executable}; Kokoro/Chatterbox wheels may fail on this Python."
    )
    return [sys.executable]


def venv_python() -> Path:
    if platform.system().lower() == "windows":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def check_system_tool(name: str, install_hint: str) -> None:
    if shutil.which(name):
        print(f"{name}: found")
    else:
        print(f"{name}: missing")
        print(f"  {install_hint}")


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


def install_optional_ml(python_exe: Path) -> None:
    optional_groups = [
        ["faster-whisper>=1.0.0"],
        ["kokoro>=0.9.4", "soundfile", "misaki[en]>=0.9.4"],
    ]
    for packages in optional_groups:
        run([str(python_exe), "-m", "pip", "install", *packages], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the local voice-to-voice assistant.")
    parser.add_argument("--skip-ml", action="store_true", help="Skip faster-whisper and Kokoro package installation.")
    parser.add_argument("--skip-model-download", action="store_true", help="Do not pull Ollama models.")
    parser.add_argument("--with-chatterbox", action="store_true", help="Try to install Chatterbox even if hardware is not ideal.")
    args = parser.parse_args()

    python_cmd = choose_python()
    if not VENV.exists():
        run([*python_cmd, "-m", "venv", str(VENV)])
    python_exe = venv_python()

    run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python_exe), "-m", "pip", "install", "-r", "requirements.txt"])
    if not args.skip_ml:
        install_optional_ml(python_exe)

    check_system_tool("ffmpeg", "Install ffmpeg and ensure it is on PATH. Windows: winget install Gyan.FFmpeg")
    check_system_tool(
        "espeak-ng",
        "Install espeak-ng for Kokoro G2P fallback. Windows: use the espeak-ng MSI from the official releases.",
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
                "config=select_config(probe_hardware()); save_config(config); "
                "print(config.model_dump_json(indent=2))"
            ),
        ]
    )

    maybe_pull_ollama_model("qwen3:4b-instruct", args.skip_model_download)
    maybe_install_chatterbox(python_exe, args.with_chatterbox)

    run([str(python_exe), "-m", "local_assistant.healthcheck"], check=False)

    backend_cmd = f"{python_exe} -m local_assistant.server"
    frontend_cmd = "cd frontend; npm run dev"
    print("\nInstall complete.")
    print(f"Backend:  {backend_cmd}")
    print(f"Frontend: {frontend_cmd}")
    print("Open:     http://127.0.0.1:5173")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
