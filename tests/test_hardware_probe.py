from local_assistant.hardware_probe import choose_gpu_backend, parse_nvidia_smi_csv, recommend_profile


def test_parse_nvidia_smi_csv():
    name, vram = parse_nvidia_smi_csv("NVIDIA RTX 4070, 12282\n")
    assert name == "NVIDIA RTX 4070"
    assert 11.9 < vram < 12.1


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
