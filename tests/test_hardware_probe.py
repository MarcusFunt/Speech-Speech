from pathlib import Path

from local_assistant import hardware_probe
from local_assistant.hardware_probe import (
    choose_gpu_backend,
    parse_linux_meminfo_total_kb,
    parse_nvidia_smi_csv,
    probe_hardware,
    recommend_profile,
)


def test_parse_nvidia_smi_csv():
    name, vram = parse_nvidia_smi_csv("NVIDIA RTX 4070, 12282\n")
    assert name == "NVIDIA RTX 4070"
    assert 11.9 < vram < 12.1


def test_parse_linux_meminfo_total_kb():
    assert parse_linux_meminfo_total_kb("MemTotal:       32670776 kB\nMemFree:         8307200 kB\n") == 32670776
    assert parse_linux_meminfo_total_kb("MemFree: 1024 kB\n") is None


def test_choose_gpu_backend_cpu():
    assert (
        choose_gpu_backend(
            nvidia_gpu=False,
            cuda_available=False,
            amd_gpu=False,
            rocm_available=False,
            apple_silicon=False,
            mps_available=False,
        )
        == "cpu"
    )


def test_recommend_profile_cuda_high():
    assert recommend_profile("cuda", 16, 32) == "high"
    assert recommend_profile("cuda", 8, 16) == "medium"
    assert recommend_profile("cpu", None, 16) == "low"


def test_ram_gb_reads_linux_proc_meminfo(monkeypatch, tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16777216 kB\n", encoding="utf-8")

    monkeypatch.setattr(hardware_probe.importlib.util, "find_spec", lambda name: None if name == "psutil" else object())
    monkeypatch.setattr(hardware_probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware_probe, "LINUX_MEMINFO_PATH", Path(meminfo))

    assert hardware_probe._ram_gb() == 16.0


def test_probe_hardware_uses_torch_cuda_when_nvidia_smi_is_unavailable(monkeypatch):
    monkeypatch.setattr(hardware_probe, "_nvidia_info", lambda runner: (False, None, None, []))
    monkeypatch.setattr(hardware_probe, "_windows_video_names", lambda runner: [])
    monkeypatch.setattr(hardware_probe, "_torch_info", lambda: (True, "12.6", 1, False, False, "RTX 3060", 12.0, []))
    monkeypatch.setattr(hardware_probe, "_ram_gb", lambda: 32.0)
    monkeypatch.setattr(hardware_probe, "_cpu_model", lambda: "x86_64")
    monkeypatch.setattr(hardware_probe.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware_probe.platform, "version", lambda: "test")
    monkeypatch.setattr(hardware_probe.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(hardware_probe.os, "cpu_count", lambda: 20)
    monkeypatch.setattr(hardware_probe.shutil, "which", lambda _name: None)

    profile = probe_hardware()

    assert profile.cuda_available is True
    assert profile.gpu_backend == "cuda"
    assert profile.nvidia_gpu is True
    assert profile.nvidia_name == "RTX 3060"
    assert profile.vram_gb == 12.0
    assert profile.torch_gpu_available is True
    assert profile.torch_cuda_build == "12.6"
