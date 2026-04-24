"""Dask helper functions."""

import logging
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from os import environ

from dask.distributed import LocalCluster, Nanny
from distributed import Scheduler, SpecCluster
from distributed.deploy.cluster import Cluster
from distributed.worker_memory import parse_memory_limit
from protein_quest.parallel import nr_cpus

try:
    import pyopencl
    from pyopencl import LogicError
except ImportError:
    pyopencl = None
    LogicError = RuntimeError


logger = logging.getLogger(__name__)


@contextmanager
def configure_dask_scheduler(
    scheduler_address: str | Cluster | None,
    name: str,
    workers_per_gpu: int = 0,
    nproc: int = 1,
) -> Iterator[str | Cluster]:
    """Configure the Dask scheduler by reusing existing or creating a new cluster.

    If scheduler_address is None then creates a local Dask cluster
    else returns scheduler_address unchanged and the callee is responsible for cluster cleanup.

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

    Yields:
        A Dask Cluster instance or a string address for the scheduler.
    """
    if scheduler_address is None:
        if workers_per_gpu > 0:
            scheduler_address = _configure_gpu_dask_scheduler(workers_per_gpu, name)
        else:
            scheduler_address = _configure_cpu_dask_scheduler(nproc, name)
        logger.info(f"Using local Dask cluster: {scheduler_address}")
        try:
            yield scheduler_address
        finally:
            scheduler_address.close()
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
        # Pass through existing scheduler address or cluster
        yield scheduler_address


def _configure_cpu_dask_scheduler(nproc: int, name: str) -> LocalCluster:
    physical_cores = nr_cpus()
    n_workers = physical_cores // nproc
    # Use single thread per worker to prevent GIL slowing down the computations
    return LocalCluster(name=name, threads_per_worker=1, n_workers=n_workers)


def _parse_visible_gpu_ids(visible_devices: str) -> list[int]:
    return [int(device.strip()) for device in visible_devices.split(",") if device.strip()]


def detect_available_gpus() -> list[int]:
    """Detect available GPU IDs.

    Preference order is CUDA/ROCR visibility environment variables,
    then OpenCL discovery.

    Returns:
        List of available GPU IDs. Empty list means no GPU detected.
    """
    visible_devices = environ.get("CUDA_VISIBLE_DEVICES")
    if visible_devices is None:
        visible_devices = environ.get("ROCR_VISIBLE_DEVICES")
    if visible_devices:
        return _parse_visible_gpu_ids(visible_devices)

    if pyopencl is None:
        return []

    try:
        platform = pyopencl.get_platforms()[0]
    except LogicError as e:
        if "PLATFORM_NOT_FOUND_KHR" in str(e):
            logger.debug("No OpenCL platform found.")
            return []
        raise
    return list(range(len(platform.get_devices())))


def build_gpu_cycler(workers_per_gpu: int = 1, gpu_ids: list[int] | None = None) -> Generator[int]:
    """Generator to cycle through GPU IDs.

    On machine with multiple GPUs and a computation that does not use a full GPU.
    This will yield GPU IDs in a round-robin fashion.

    - If gpu_ids is empty, it will yield 0 indefinitely.
    - If workers_per_gpu>0 and gpu_ids=[2], it will yield 2 indefinitely.
    - If workers_per_gpu=1 and gpu_ids=[0, 2], it will yield 0, 2 indefinitely.
    - If workers_per_gpu=4 and gpu_ids=[0, 2], it will yield 0, 2, 0, 2, 0, 2, 0, 2 indefinitely.
    """
    if gpu_ids is None:
        gpu_ids = detect_available_gpus()

    if not gpu_ids:
        while True:
            yield 0
    else:
        while True:
            for _ in range(workers_per_gpu):
                yield from gpu_ids


def _configure_gpu_dask_scheduler(workers_per_gpu: int, cluster_name: str) -> SpecCluster:
    if pyopencl is None:
        msg = "pyopencl is required for GPU support in PowerFit."
        raise ImportError(msg)
        # Assume first platform is quickest
    platform = pyopencl.get_platforms()[0]
    gpu_ids = detect_available_gpus()
    # Below is similar to https://github.com/rapidsai/dask-cuda/blob/main/dask_cuda/local_cuda_cluster.py
    # but more minimalistic and with AMD support
    n_gpus = len(gpu_ids)
    if platform.vendor not in ["NVIDIA Corporation", "Advanced Micro Devices, Inc."] and n_gpus > 1:
        msg = f"Unsupported GPU vendor: {platform.vendor} for multiple GPU support."
        raise ValueError(msg)
    env_name = "CUDA_VISIBLE_DEVICES" if platform.vendor == "NVIDIA Corporation" else "ROCR_VISIBLE_DEVICES"
    worker_specs = {}
    # The computation besides using GPU also uses Python,
    # so we can not use multiple threads
    # as it would slow down the computations due to GIL.
    for i in gpu_ids:
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
