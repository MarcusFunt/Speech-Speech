from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field


GpuBackend = Literal["cuda", "rocm", "mps", "cpu", "unknown"]
RecommendedProfile = Literal["low", "medium", "high", "experimental"]
LINUX_MEMINFO_PATH = Path("/proc/meminfo")


class HardwareProfile(BaseModel):
    os_name: str
    os_version: str
    cpu_model: str | None = None
    cpu_cores: int
    ram_gb: float | None = None
    python_version: str
    nvidia_gpu: bool = False
    nvidia_name: str | None = None
    cuda_available: bool = False
    nvidia_vram_gb: float | None = None
    amd_gpu: bool = False
    rocm_available: bool = False
    apple_silicon: bool = False
    mps_available: bool = False
    torch_gpu_available: bool = False
    torch_cuda_build: str | None = None
    torch_device_count: int = 0
    gpu_backend: GpuBackend = "unknown"
    vram_gb: float | None = None
    ffmpeg_installed: bool = False
    espeak_installed: bool = False
    recommended_profile: RecommendedProfile = "low"
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], int], CommandResult]


def _run_command(command: list[str], timeout_s: int = 8) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        return CommandResult(1, "", str(exc))


def _cpu_model() -> str | None:
    model = platform.processor() or platform.machine()
    if model:
        return model.strip()
    if platform.system().lower() == "windows":
        result = _run_command(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name",
            ]
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _ram_gb() -> float | None:
    if importlib.util.find_spec("psutil"):
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 2)
    system = platform.system().lower()
    if system == "windows":
        result = _run_command(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
            ]
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return round(int(result.stdout.strip()) / (1024**3), 2)
    if system == "linux":
        try:
            total_kb = parse_linux_meminfo_total_kb(LINUX_MEMINFO_PATH.read_text(encoding="utf-8"))
        except OSError:
            total_kb = None
        if total_kb is not None:
            return round(total_kb / (1024**2), 2)
    return None


def parse_nvidia_smi_csv(output: str) -> tuple[str | None, float | None]:
    """Parse `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`."""
    first = next((line.strip() for line in output.splitlines() if line.strip()), "")
    if not first:
        return None, None
    parts = [part.strip() for part in first.split(",")]
    name = parts[0] if parts else None
    vram_gb: float | None = None
    if len(parts) >= 2:
        try:
            vram_gb = round(float(parts[1]) / 1024, 2)
        except ValueError:
            vram_gb = None
    return name, vram_gb


def parse_linux_meminfo_total_kb(output: str) -> int | None:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    return None


def _nvidia_info(runner: CommandRunner) -> tuple[bool, str | None, float | None, list[str]]:
    notes: list[str] = []
    if not shutil.which("nvidia-smi"):
        return False, None, None, notes
    result = runner(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ],
        8,
    )
    if result.returncode != 0:
        notes.append(f"nvidia-smi failed: {result.stderr.strip() or result.stdout.strip()}")
        return False, None, None, notes
    name, vram_gb = parse_nvidia_smi_csv(result.stdout)
    return bool(name), name, vram_gb, notes


def _windows_video_names(runner: CommandRunner) -> list[str]:
    if platform.system().lower() != "windows":
        return []
    result = runner(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | ConvertTo-Json",
        ],
        8,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        value = json.loads(result.stdout)
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
    except json.JSONDecodeError:
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return []


def _torch_info() -> tuple[bool, str | None, int, bool, bool, str | None, float | None, list[str]]:
    notes: list[str] = []
    if not importlib.util.find_spec("torch"):
        return False, None, 0, False, False, None, None, ["torch is not installed"]
    try:
        import torch

        cuda_build = getattr(torch.version, "cuda", None)
        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
        mps_available = bool(
            getattr(torch.backends, "mps", None)
            and torch.backends.mps.is_available()
            and torch.backends.mps.is_built()
        )
        rocm_available = bool(getattr(torch.version, "hip", None))
        cuda_device_name: str | None = None
        cuda_vram_gb: float | None = None
        if cuda_available and device_count > 0:
            try:
                properties = torch.cuda.get_device_properties(0)
                cuda_device_name = str(getattr(properties, "name", "") or "").strip() or None
                total_memory = getattr(properties, "total_memory", None)
                if isinstance(total_memory, (int, float)) and total_memory > 0:
                    cuda_vram_gb = round(float(total_memory) / (1024**3), 2)
            except Exception as exc:  # pragma: no cover - depends on native torch install
                notes.append(f"torch CUDA device probe failed: {exc}")
        return cuda_available, cuda_build, device_count, mps_available, rocm_available, cuda_device_name, cuda_vram_gb, notes
    except Exception as exc:  # pragma: no cover - depends on native torch install
        notes.append(f"torch probe failed: {exc}")
        return False, None, 0, False, False, None, None, notes


def choose_gpu_backend(
    *,
    nvidia_gpu: bool,
    cuda_available: bool,
    amd_gpu: bool,
    rocm_available: bool,
    apple_silicon: bool,
    mps_available: bool,
) -> GpuBackend:
    if nvidia_gpu or cuda_available:
        return "cuda" if cuda_available else "unknown"
    if amd_gpu:
        return "rocm" if rocm_available else "unknown"
    if apple_silicon:
        return "mps" if mps_available else "cpu"
    return "cpu"


def recommend_profile(gpu_backend: GpuBackend, vram_gb: float | None, ram_gb: float | None) -> RecommendedProfile:
    if gpu_backend == "cuda":
        if vram_gb and vram_gb >= 12:
            return "high"
        if vram_gb and vram_gb >= 6:
            return "medium"
        return "low"
    if gpu_backend in {"mps", "rocm"}:
        return "medium" if (ram_gb or 0) >= 16 else "low"
    return "low"


def probe_hardware(runner: CommandRunner = _run_command) -> HardwareProfile:
    notes: list[str] = []
    nvidia_gpu, nvidia_name, nvidia_vram_gb, nvidia_notes = _nvidia_info(runner)
    notes.extend(nvidia_notes)

    video_names = _windows_video_names(runner)
    amd_gpu = any("amd" in name.lower() or "radeon" in name.lower() for name in video_names)
    apple_silicon = platform.system().lower() == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    (
        torch_cuda_available,
        torch_cuda_build,
        torch_device_count,
        mps_available,
        rocm_available,
        torch_cuda_name,
        torch_cuda_vram_gb,
        torch_notes,
    ) = _torch_info()
    notes.extend(torch_notes)

    if torch_cuda_available:
        nvidia_gpu = True
        if not nvidia_name:
            nvidia_name = torch_cuda_name
        if nvidia_vram_gb is None:
            nvidia_vram_gb = torch_cuda_vram_gb

    cuda_available = bool(torch_cuda_available and torch_device_count > 0)
    torch_gpu_available = bool(cuda_available or mps_available or rocm_available)
    if nvidia_gpu and not cuda_available:
        if torch_cuda_build:
            notes.append(
                f"NVIDIA GPU detected, but torch CUDA {torch_cuda_build} cannot access a CUDA device in this runtime"
            )
        else:
            notes.append("NVIDIA GPU detected, but the installed torch build has no CUDA support")
    gpu_backend = choose_gpu_backend(
        nvidia_gpu=nvidia_gpu,
        cuda_available=cuda_available,
        amd_gpu=amd_gpu,
        rocm_available=rocm_available,
        apple_silicon=apple_silicon,
        mps_available=mps_available,
    )
    vram_gb = nvidia_vram_gb if gpu_backend in {"cuda", "unknown"} else None
    ram_gb = _ram_gb()

    return HardwareProfile(
        os_name=platform.system(),
        os_version=platform.version(),
        cpu_model=_cpu_model(),
        cpu_cores=os.cpu_count() or 1,
        ram_gb=ram_gb,
        python_version=sys.version.split()[0],
        nvidia_gpu=nvidia_gpu,
        nvidia_name=nvidia_name,
        cuda_available=cuda_available,
        nvidia_vram_gb=nvidia_vram_gb,
        amd_gpu=amd_gpu,
        rocm_available=rocm_available,
        apple_silicon=apple_silicon,
        mps_available=mps_available,
        torch_gpu_available=torch_gpu_available,
        torch_cuda_build=torch_cuda_build,
        torch_device_count=torch_device_count,
        gpu_backend=gpu_backend,
        vram_gb=vram_gb,
        ffmpeg_installed=shutil.which("ffmpeg") is not None,
        espeak_installed=shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None,
        recommended_profile=recommend_profile(gpu_backend, vram_gb, ram_gb),
        notes=list(dict.fromkeys(notes)),
    )


if __name__ == "__main__":
    print(probe_hardware().model_dump_json(indent=2))
