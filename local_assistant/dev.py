from __future__ import annotations

import argparse
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, start: int) -> int:
    port = start
    while port <= 65535:
        if port_is_free(host, port):
            return port
        port += 1
    raise RuntimeError(f"No free TCP port found on {host} starting at {start}")


def npm_command() -> list[str]:
    for name in ["npm.cmd", "npm"]:
        path = shutil.which(name)
        if path:
            return [path]
    raise SystemExit("npm not found. Install Node.js/npm before running the web frontend.")


def terminate(processes: list[subprocess.Popen]) -> None:
    if os.name == "nt":
        for process in processes:
            if process.poll() is None:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                except OSError:
                    pass
        deadline = time.monotonic() + 5
        for process in processes:
            if process.poll() is not None:
                continue
            remaining = max(0.1, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
        for process in processes:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        return

    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in processes:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


def raise_keyboard_interrupt(signum: int, _frame: object) -> None:
    raise KeyboardInterrupt(f"received signal {signum}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run backend and frontend dev servers on free local ports.")
    parser.add_argument("--host", default="127.0.0.1", help="Host used by both dev servers.")
    parser.add_argument("--backend-port", type=int, default=8000, help="First backend port to try.")
    parser.add_argument("--frontend-port", type=int, default=5173, help="First frontend port to try.")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, raise_keyboard_interrupt)
    signal.signal(signal.SIGTERM, raise_keyboard_interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, raise_keyboard_interrupt)

    backend_port = find_free_port(args.host, args.backend_port)
    frontend_port = find_free_port(args.host, args.frontend_port)
    backend_url = f"http://{args.host}:{backend_port}"
    frontend_url = f"http://{args.host}:{frontend_port}"
    frontend_origins = ",".join(
        list(
            dict.fromkeys(
                [
                    frontend_url,
                    f"http://localhost:{frontend_port}",
                    f"http://127.0.0.1:{frontend_port}",
                ]
            )
        )
    )

    backend_env = os.environ.copy()
    backend_env["LOCAL_ASSISTANT_CORS_ORIGINS"] = frontend_origins

    frontend_env = os.environ.copy()
    frontend_env["VITE_API_BASE"] = backend_url
    npm = npm_command()

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    processes: list[subprocess.Popen] = []
    try:
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "local_assistant.server:app",
                "--host",
                args.host,
                "--port",
                str(backend_port),
            ],
            cwd=ROOT,
            env=backend_env,
            creationflags=creationflags,
        )
        processes.append(backend)
        frontend = subprocess.Popen(
            [
                *npm,
                "run",
                "dev",
                "--",
                "--host",
                args.host,
                "--port",
                str(frontend_port),
                "--strictPort",
            ],
            cwd=FRONTEND_DIR,
            env=frontend_env,
            creationflags=creationflags,
        )
        processes.append(frontend)
    except Exception:
        terminate(processes)
        raise

    print("\nDev servers starting.")
    print(f"Backend:  {backend_url}")
    print(f"Frontend: {frontend_url}")
    print(f"CORS:     {frontend_origins}")
    print("Press Ctrl+C to stop both processes.\n")
    sys.stdout.flush()

    try:
        while True:
            if backend.poll() is not None:
                print(f"Backend exited with code {backend.returncode}; stopping frontend.")
                return backend.returncode or 0
            if frontend.poll() is not None:
                print(f"Frontend exited with code {frontend.returncode}; stopping backend.")
                return frontend.returncode or 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping dev servers.")
        return 130
    finally:
        terminate(processes)


if __name__ == "__main__":
    raise SystemExit(main())
