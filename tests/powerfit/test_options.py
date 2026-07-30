from pathlib import Path

import pytest

from protein_detective.powerfit.options import GpuBackend, PowerfitOptions


@pytest.mark.parametrize(
    ("backend", "gpu_id", "expected"),
    [
        ("cuda", 2, "cuda:2"),
        ("opencl", 2, "0:2"),
    ],
)
def test_format_gpu_device(backend: GpuBackend, gpu_id: int, expected: str):
    options = PowerfitOptions(gpu_backend=backend)
    assert options.format_gpu_device(gpu_id) == expected


def test_to_command_uses_formatted_gpu_device_for_backend():
    options = PowerfitOptions(gpu_backend="cuda", cpu=False)
    command = options.to_command(
        density_map=Path("density.mrc"),
        resolution=3.0,
        template=Path("template.pdb"),
        out_dir=Path("out"),
        gpu_cycler=(gpu_id for gpu_id in [3]),
    )
    assert "--gpu cuda:3" in command
