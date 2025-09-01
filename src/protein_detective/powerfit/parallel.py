"""Dask helper functions."""

import logging
from collections.abc import Generator
from pathlib import Path

from dask.distributed import LocalCluster, Nanny
from distributed import Scheduler, SpecCluster
from distributed.deploy.cluster import Cluster
from distributed.worker_memory import parse_memory_limit
from psutil import cpu_count

from protein_detective.db import PowerfitOptions
from protein_detective.powerfit.run import run as powerfit_run

try:
    import pyopencl
    from pyopencl import LogicError
except ImportError:
    pyopencl = None
    LogicError = RuntimeError


logger = logging.getLogger(__name__)


def configure_dask_scheduler(
    scheduler_address: str | Cluster | None,
    name: str,
    workers_per_gpu: int = 0,
    nproc: int = 1,
) -> str | Cluster:
    """Configure the Dask scheduler by reusing existing or creating a new cluster.

    When creating a local GPU cluster on a machine with multiple GPUs,
    it will start workers which each can only see a single GPU.

    Args:
        scheduler_address: Address of the Dask scheduler to connect to, or None for local cluster.
        name: Name for the Dask cluster.
        workers_per_gpu: Number of workers per GPU.
            If > 0, a GPU cluster will be configured otherwise a CPU cluster.
        nproc: Number of processes to use per worker for CPU support.

    Raises:
        ImportError: If GPU support is requested but pyopencl is not installed.
        ValueError: If multiple GPUs are detected but the vendor is unsupported.

    Returns:
        A Dask Cluster instance or a string address for the scheduler.
    """
    if scheduler_address is None:
        if workers_per_gpu > 0:
            scheduler_address = _configure_gpu_dask_scheduler(workers_per_gpu, name)
        else:
            scheduler_address = _configure_cpu_dask_scheduler(nproc, name)
        logger.info(f"Using local Dask cluster: {scheduler_address}")
    else:
        if workers_per_gpu > 0:
            if pyopencl is None:
                msg = "pyopencl is required for GPU support in PowerFit."
                raise ImportError(msg)
            if len(pyopencl.get_platforms()[0].get_devices()) > 1:
                logger.warning(
                    "Multiple GPUs detected, make sure each worker has a pinned GPU using "
                    "CUDA_VISIBLE_DEVICES or ROCR_VISIBLE_DEVICES environment variables."
                )

    return scheduler_address


def _configure_cpu_dask_scheduler(nproc: int, name: str) -> LocalCluster:
    physical_cores = cpu_count(logical=False)
    if physical_cores is None:
        msg = "Cannot determine number of logical CPU cores."
        raise ValueError(msg)
    n_workers = physical_cores // nproc
    # Use single thread per worker to prevent GIL slowing down the computations
    return LocalCluster(name=name, threads_per_worker=1, n_workers=n_workers)


def nr_gpus() -> int:
    """The number of available GPUs on the system.

    Returns:
        Number of GPUs available
    """
    if pyopencl is None:
        return 0

    try:
        platform = pyopencl.get_platforms()[0]
    except LogicError as e:
        if "PLATFORM_NOT_FOUND_KHR" in str(e):
            logger.debug("No OpenCL platform found.")
            return 0
        raise
    gpus = platform.get_devices()
    return len(gpus)


def build_gpu_cycler(workers_per_gpu: int = 1, n_gpus: int = nr_gpus()) -> Generator[int]:
    """Generator to cycle through GPU indices.

    On machine with multiple GPUs and a computation that does not use a full GPU.
    This will yield GPU indices in a round-robin fashion.

    - If n_gpus is set to 0, it will yield 0 indefinitely.
    - If workers_per_gpu>0 and n_gpus=1, it will yield 0 indefinitely.
    - If workers_per_gpu=1 and n_gpus=2, it will yield 0, 1 indefinitely.
    - If workers_per_gpu=4 and n_gpus=2, it will yield 0, 1, 0, 1, 0, 1, 0, 1 indefinitely.
    """
    if n_gpus == 0:
        while True:
            yield 0
    else:
        while True:
            for _ in range(workers_per_gpu):
                yield from range(n_gpus)


def _configure_gpu_dask_scheduler(workers_per_gpu: int, cluster_name: str) -> SpecCluster:
    if pyopencl is None:
        msg = "pyopencl is required for GPU support in PowerFit."
        raise ImportError(msg)
        # Assume first platform is quickest
    platform = pyopencl.get_platforms()[0]
    gpus = platform.get_devices()
    # Below is similar to https://github.com/rapidsai/dask-cuda/blob/main/dask_cuda/local_cuda_cluster.py
    # but more minimalistic and with AMD support
    n_gpus = len(gpus)
    if platform.vendor not in ["NVIDIA Corporation", "Advanced Micro Devices, Inc."] and n_gpus > 1:
        msg = f"Unsupported GPU vendor: {platform.vendor} for multiple GPU support."
        raise ValueError(msg)
    env_name = "CUDA_VISIBLE_DEVICES" if platform.vendor == "NVIDIA Corporation" else "ROCR_VISIBLE_DEVICES"
    worker_specs = {}
    # The computation besides using GPU also uses Python,
    # so we can not use multiple threads
    # as it would slow down the computations due to GIL.
    for i in range(n_gpus):
        for j in range(workers_per_gpu):
            worker_spec = {
                "cls": Nanny,
                "options": {
                    "memory_limit": parse_memory_limit("auto", 1, n_gpus * workers_per_gpu, logger=logger),
                    "nthreads": 1,
                    "dashboard_address": ":0",
                    "env": {env_name: str(i)},
                },
            }
            worker_specs[f"gpu-worker-{i}-{j}"] = worker_spec
    scheduler_address = SpecCluster(
        workers=worker_specs,
        scheduler={
            "cls": Scheduler,
            "options": {
                "dashboard_address": ":8787",
            },
        },
        name=cluster_name,
    )
    logger.info(f"Found {n_gpus} GPUs, using {workers_per_gpu} workers per GPU.")
    return scheduler_address


def powerfit_worker(pdb_file: Path, density_map_target: Path, powerfit_run_root_dir: Path, options: PowerfitOptions):
    """Worker function for running PowerFit on a single PDB file.

    Args:
        pdb_file: Path to the PDB file to process
        density_map_target: Path to the density map file
        powerfit_run_root_dir: Root directory for PowerFit results
        options: PowerFit options
    """
    result_dir = powerfit_run_root_dir / pdb_file.stem
    logger.info(f"Running PowerFit on {density_map_target} against {pdb_file} with options: {options}")
    with density_map_target.open("rb") as density_map:
        powerfit_run(density_map, pdb_file, result_dir, options)
