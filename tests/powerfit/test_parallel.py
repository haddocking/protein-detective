from protein_detective.powerfit.parallel import build_gpu_cycler


def test_gpu_cycler_many():
    cycler = build_gpu_cycler(workers_per_gpu=3, n_gpus=4)
    cycles = [next(cycler) for _ in range(16)]
    assert cycles == [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3]


def test_gpu_cycler_none():
    cycler = build_gpu_cycler(workers_per_gpu=1, n_gpus=0)
    cycles = [next(cycler) for _ in range(10)]
    assert cycles == [0] * 10
