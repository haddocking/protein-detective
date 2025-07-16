"""Dask helper functions."""

import logging
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
except ImportError:
    pyopencl = None


logger = logging.getLogger(__name__)


def configure_dask_scheduler(
    scheduler_adress: str | Cluster | None, options: PowerfitOptions, powerfit_run_id: int
) -> str | Cluster:
    """Configure the Dask scheduler based on the provided options and run ID.

    Args:
        scheduler_adress: Address of the Dask scheduler to connect to, or None for local cluster.
        options: PowerFit options containing GPU and nproc settings.
        powerfit_run_id: ID of the PowerFit run for naming the cluster.

    Raises:
        ImportError: If GPU support is requested but pyopencl is not installed.
        ValueError: If multiple GPUs are detected but the vendor is unsupported.

    Returns:
        A Dask Cluster instance or a string address for the scheduler.
    """
    if scheduler_adress is None:
        if options.gpu > 0:
            if pyopencl is None:
                msg = "pyopencl is required for GPU support in PowerFit."
                raise ImportError(msg)
            platform = pyopencl.get_platforms()[0]
            gpus = platform.get_devices()
            # Below is similar to https://github.com/rapidsai/dask-cuda/blob/main/dask_cuda/local_cuda_cluster.py
            # but more minimalistic and with AMD support
            n_workers = len(gpus)
            threads_per_worker = options.gpu
            if platform.vendor not in ["NVIDIA Corporation", "Advanced Micro Devices, Inc."] and n_workers > 1:
                msg = f"Unsupported GPU vendor: {platform.vendor} for multiple GPU support."
                raise ValueError(msg)
            env_name = "CUDA_VISIBLE_DEVICES" if platform.vendor == "NVIDIA Corporation" else "ROCR_VISIBLE_DEVICES"
            # running multiple thread per worker is slower than more single-threaded workers
            # TODO change to multiple single threaded workers per GPU
            worker_specs = {
                f"gpu-worker-{i}": {
                    "cls": Nanny,
                    "options": {
                        "memory_limit": parse_memory_limit("auto", 1, n_workers, logger=logger),
                        "nthreads": threads_per_worker,
                        "dashboard_address": ":0",
                        "env": {env_name: str(i)},
                    },
                }
                for i in range(n_workers)
            }
            scheduler_adress = SpecCluster(
                workers=worker_specs,
                scheduler={
                    "cls": Scheduler,
                    "options": {
                        "dashboard_address": ":8787",
                    },
                },
                name=f"powerfit-run-{powerfit_run_id}",
            )
            logger.info(f"Found {n_workers} GPUs, using {threads_per_worker} threads per GPU worker.")
        else:
            physical_cores = cpu_count(logical=False)
            if physical_cores is None:
                msg = "Cannot determine number of logical CPU cores."
                raise ValueError(msg)
            n_workers = physical_cores // options.nproc
            # Use single thread per worker to prevent GIL slowing down the computations
            scheduler_adress = LocalCluster(
                name=f"powerfit-run-{powerfit_run_id}", threads_per_worker=1, n_workers=n_workers
            )
        logger.info(f"Using local Dask cluster: {scheduler_adress}")
    else:
        if options.gpu > 0:
            if pyopencl is None:
                msg = "pyopencl is required for GPU support in PowerFit."
                raise ImportError(msg)
            if len(pyopencl.get_platforms()[0].get_devices()) > 1:
                logger.warning(
                    "Multiple GPUs detected, make sure each worker has a pinned GPU using "
                    "CUDA_VISIBLE_DEVICES or ROCR_VISIBLE_DEVICES environment variables."
                )

    return scheduler_adress


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
