"""Dask helper functions."""

import logging
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from importlib import import_module
from os import environ

from dask.distributed import LocalCluster, Nanny
from distributed import Scheduler, SpecCluster
from distributed.deploy.cluster import Cluster
from distributed.worker_memory import parse_memory_limit
from powerfit_em.gpu import cuda_available, opencl_available
from protein_quest.parallel import nr_cpus

from protein_detective.powerfit.options import GpuBackend

logger = logging.getLogger(__name__)


def _opencl_unavailable_error() -> ImportError:
    msg = "OpenCL backend requested, but OpenCL is not available."
    return ImportError(msg)


def _cuda_unavailable_error() -> ImportError:
    msg = "CUDA backend requested, but CUDA is not available."
    return ImportError(msg)


def _opencl_platform_vendor() -> str:
    cl = import_module("pyopencl")
    try:
        platforms = cl.get_platforms()
    except cl.LogicError as e:
        raise _opencl_unavailable_error() from e
    if not platforms:
        raise _opencl_unavailable_error()
    return platforms[0].vendor


@contextmanager
def configure_dask_scheduler(
    scheduler_address: str | Cluster | None,
    name: str,
    workers_per_gpu: int = 0,
    nproc: int = 1,
    gpu_backend: GpuBackend = "opencl",
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
        gpu_backend: GPU backend to use for local GPU cluster setup.

    Raises:
        ImportError: If GPU support is requested but the selected backend is unavailable.
        ValueError: If multiple GPUs are detected but the vendor is unsupported.

    Yields:
        A Dask Cluster instance or a string address for the scheduler.
    """
    if scheduler_address is None:
        if workers_per_gpu > 0:
            scheduler_address = _configure_gpu_dask_scheduler(workers_per_gpu, name, gpu_backend)
        else:
            scheduler_address = _configure_cpu_dask_scheduler(nproc, name)
        logger.info(f"Using local Dask cluster: {scheduler_address}")
        try:
            yield scheduler_address
        finally:
            scheduler_address.close()
    else:
        if workers_per_gpu > 0:
            if gpu_backend == "opencl" and not opencl_available():
                raise _opencl_unavailable_error()
            if gpu_backend == "cuda" and not cuda_available():
                raise _cuda_unavailable_error()
            if len(detect_available_gpus(gpu_backend)) > 1:
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


def _detect_cuda_devices() -> list[int]:
    """Detect available CUDA device IDs using cupy.

    Returns:
        List of device IDs. Empty list if cupy unavailable or device detection fails.
    """
    try:
        cupy = import_module("cupy")
        device_count = cupy.cuda.runtime.getDeviceCount()
        return list(range(device_count))
    except ImportError:
        return []
    except (RuntimeError, AttributeError):
        # Device count query or API access failed
        return []


def detect_available_gpus(gpu_backend: GpuBackend = "opencl", cuda_devices: list[int] | None = None) -> list[int]:
    """Detect available GPU IDs.

    For CUDA backend: CuPy handles CUDA_VISIBLE_DEVICES/ROCR_VISIBLE_DEVICES internally.
    For OpenCL backend: Checks environment variables before falling back to OpenCL discovery.

    Args:
        gpu_backend: Backend used for GPU discovery.
        cuda_devices: Optional list of CUDA device IDs to use instead of detecting.
            If provided, bypasses cuda_available() check. Useful for testing.

    Returns:
        List of available GPU IDs. Empty list means no GPU detected.
    """
    if gpu_backend == "cuda":
        if cuda_devices is not None:
            return cuda_devices
        if not cuda_available():
            return []
        return _detect_cuda_devices()

    visible_devices = environ.get("CUDA_VISIBLE_DEVICES") or environ.get("ROCR_VISIBLE_DEVICES")
    # CUDA_VISIBLE_DEVICES can also have GPU UUID strings as values.
    # see https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html
    # As can ROCR_VISIBLE_DEVICES
    # see https://rocm.docs.amd.com/en/latest/reference/environment-variables/index.html
    # Slurm uses integers, so low priority to handle GPU UUID strings
    # as Slurm cluster is most likely place with multiple GPUs.
    # see https://slurm.schedmd.com/gres.html
    if visible_devices:
        return _parse_visible_gpu_ids(visible_devices)

    if not opencl_available():
        return []

    cl = import_module("pyopencl")
    try:
        platform = cl.get_platforms()[0]
    except (IndexError, cl.LogicError) as e:
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


def _configure_gpu_dask_scheduler(workers_per_gpu: int, cluster_name: str, gpu_backend: GpuBackend) -> SpecCluster:
    if gpu_backend == "opencl" and not opencl_available():
        raise _opencl_unavailable_error()
    if gpu_backend == "cuda" and not cuda_available():
        raise _cuda_unavailable_error()
    gpu_ids = detect_available_gpus(gpu_backend)
    # Below is similar to https://github.com/rapidsai/dask-cuda/blob/main/dask_cuda/local_cuda_cluster.py
    # but more minimalistic and with AMD support
    n_gpus = len(gpu_ids)
    if gpu_backend == "opencl":
        platform_vendor = _opencl_platform_vendor()
        if platform_vendor not in ["NVIDIA Corporation", "Advanced Micro Devices, Inc."] and n_gpus > 1:
            msg = f"Unsupported GPU vendor: {platform_vendor} for multiple GPU support."
            raise ValueError(msg)
        env_name = "CUDA_VISIBLE_DEVICES" if platform_vendor == "NVIDIA Corporation" else "ROCR_VISIBLE_DEVICES"
    else:
        env_name = "CUDA_VISIBLE_DEVICES"
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
