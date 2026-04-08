import logging
from os import environ
from pathlib import Path

from powerfit_em.analyzer import Analyzer
from powerfit_em.powerfit import (
    get_gpu_queue,
    setup_rotational_matrix,
    setup_target,
    setup_template_structure,
)
from powerfit_em.powerfitter import PowerFitter

from protein_detective.db import PowerfitOptions

logger = logging.getLogger(__name__)


# Cached fitter on each worker
pf: PowerFitter | None = None


def powerfit_worker(
    template_structure: Path, density_map_target: Path, powerfit_run_root_dir: Path, options: PowerfitOptions
):
    """Worker function for running PowerFit on a template structure file.

    Args:
        template_structure: Path to the template structure file to process
        density_map_target: Path to the density map file
        powerfit_run_root_dir: Root directory for PowerFit results
        options: PowerFit options
    """
    # This function is a refactor of powerfit_em.powerfit.powerfit function that caches
    # the PowerFitter instance on each worker to avoid re-initialization overhead and reuse of GPU queue.
    global pf  # noqa: PLW0603
    result_dir = powerfit_run_root_dir / template_structure.stem
    solutions = result_dir / "solutions.out"
    logger.info(f"Running PowerFit on {density_map_target} against {template_structure} with options: {options}")
    if solutions.exists():
        logger.info(f"Skipping powerfit run, solutions file already exists: {solutions}")
        return
    if pf is None:
        gpu: str | None = None
        if options.gpu:
            visible_devices = environ.get("CUDA_VISIBLE_DEVICES", environ.get("ROCR_VISIBLE_DEVICES"))
            if visible_devices:
                gpu = f"0:{visible_devices}"
        queue = None

        if gpu:
            queue = get_gpu_queue(gpu)

        with density_map_target.open("rb") as f:
            target = setup_target(
                f,
                options.resolution,
                options.no_resampling,
                options.resampling_rate,
                options.no_trimming,
                options.trimming_cutoff,
            )

        rotmat = setup_rotational_matrix(options.angle)

        with template_structure.open("rb") as f:
            _, template, mask, z_sigma = setup_template_structure(
                f, None, target, options.resolution, options.core_weighted
            )

        pf = PowerFitter(target, rotmat, template, mask, queue, options.nproc, laplace=options.laplace)
    else:
        logger.info("Reusing cached PowerFitter instance on worker.")
        with template_structure.open("rb") as f:
            _, template, mask, z_sigma = setup_template_structure(
                f, None, pf._target, options.resolution, options.core_weighted
            )
        pf.set_template(template, mask)

    pf.scan(progress=None)
    analyzer = Analyzer(
        pf.lcc,
        pf._rotations,
        pf.rot,
        voxelspacing=pf._target.voxelspacing,
        origin=pf._target.origin,
        z_sigma=z_sigma,
    )
    result_dir.mkdir(parents=True, exist_ok=True)
    analyzer.tofile(str(solutions), delimiter=",")
    logger.info(f"PowerFit results saved to {solutions}")


def clear_worker_cache():
    """Clear cached objects on the worker.

    Call this function if you want to call powerfit_worker
    again with different arguments except the template_structure.

    Example:

        from dask.distributed import Client
        client = Client()  # or your existing client
        from protein_detective.powerfit.run import clear_worker_cache
        client.run(clear_worker_cache)

    """
    global pf  # noqa: PLW0603
    pf = None
