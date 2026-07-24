from pathlib import Path

import pytest

from protein_detective.powerfit.options import PowerfitOptions, parse_first_visible_gpu_id


@pytest.mark.parametrize(
    ("backend", "gpu_id", "expected"),
    [
        ("cuda", 2, "cuda:2"),
        ("opencl", 2, "0:2"),
    ],
)
def test_format_gpu_device(backend, gpu_id, expected):
    options = PowerfitOptions(gpu_backend=backend)
    assert options.format_gpu_device(gpu_id) == expected


@pytest.mark.parametrize(
    ("visible_devices", "expected"),
    [
        (None, 0),
        ("", 0),
        (",2", 0),
        (" ", 0),
        ("2", 2),
        ("2,5", 2),
        (" 7 , 8 ", 7),
        ("not-an-int,1", 0),
    ],
)
def test_parse_first_visible_gpu_id(visible_devices, expected):
    assert parse_first_visible_gpu_id(visible_devices) == expected


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
