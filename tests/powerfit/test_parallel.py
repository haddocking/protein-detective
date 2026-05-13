import pytest

from protein_detective.powerfit.parallel import build_gpu_cycler, detect_available_gpus


def test_gpu_cycler_many():
    cycler = build_gpu_cycler(workers_per_gpu=3, gpu_ids=[0, 1, 2, 3])
    cycles = [next(cycler) for _ in range(16)]
    assert cycles == [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]


def test_gpu_cycler_none():
    cycler = build_gpu_cycler(workers_per_gpu=1, gpu_ids=[])
    cycles = [next(cycler) for _ in range(10)]
    assert cycles == [0] * 10


def test_gpu_cycler_non_contiguous_gpu_ids():
    cycler = build_gpu_cycler(workers_per_gpu=1, gpu_ids=[0, 2])
    cycles = [next(cycler) for _ in range(8)]
    assert cycles == [0, 2, 0, 2, 0, 2, 0, 2]


def test_detect_available_gpus_from_cuda_visible_devices(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,5")
    monkeypatch.delenv("ROCR_VISIBLE_DEVICES", raising=False)
    assert detect_available_gpus() == [2, 5]


def test_detect_available_gpus_from_rocr_visible_devices(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setenv("ROCR_VISIBLE_DEVICES", "1,3")
    assert detect_available_gpus() == [1, 3]


@pytest.mark.parametrize(
    ("cuda_devices_arg", "expected"),
    [
        ([0, 1], [0, 1]),
        (None, []),
    ],
)
def test_detect_available_gpus_for_cuda_backend(monkeypatch, cuda_devices_arg, expected):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "4,6")
    monkeypatch.delenv("ROCR_VISIBLE_DEVICES", raising=False)
    # When CUDA_VISIBLE_DEVICES="4,6", CuPy sees 2 devices and reports [0, 1]
    # When cuda_devices is provided, cuda_available() check is bypassed
    assert detect_available_gpus("cuda", cuda_devices=cuda_devices_arg) == expected
