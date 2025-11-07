import logging
from functools import partial
from pathlib import Path
from typing import BinaryIO

from powerfit_em.analyzer import Analyzer
from powerfit_em.powerfit import (
    get_gpu_queue,
    powerfit,
    setup_rotational_matrix,
    setup_target,
    setup_template_structure,
)
from powerfit_em.powerfitter import PowerFitter
from tqdm.auto import tqdm

from protein_detective.db import PowerfitOptions

logger = logging.getLogger(__name__)


def run(density_map: BinaryIO, structure: Path, result_dir: Path, options: PowerfitOptions):
    """Run powerfit on the given density map and structure, saving results to result_dir.

    If resuls_dir / solutions.out already exists, it skips the run.

    Args:
        density_map: The density map file to fit the structure into.
        structure: The path to the prepared PDB structure file.
        result_dir: The directory where results will be saved.
        options: Options for running powerfit, including resolution, angle, etc.

    """
    solutions = result_dir / "solutions.out"
    if solutions.exists():
        # For example session1/powerfit/11/A8MT69_pdb4ne5.ent_B2A/solutions.out
        # The 11 is the powerfit_run_id which maps to values in to options
        # So if exists then powerfit was already run with same options
        logger.info(f"Skipping powerfit run, solutions file already exists: {solutions}")
        return

    gpu: str | None = None
    if options.gpu:
        gpu = "0:0"

    # disable progress bar, use parent template_structures as progress bar
    progress = partial(tqdm, disable=True)

    with structure.open(mode="br") as template_structure:
        powerfit(
            target_volume=density_map,
            resolution=options.resolution,
            template_structure=template_structure,
            angle=options.angle,
            laplace=options.laplace,
            core_weighted=options.core_weighted,
            no_resampling=options.no_resampling,
            resampling_rate=options.resampling_rate,
            no_trimming=options.no_trimming,
            trimming_cutoff=options.trimming_cutoff,
            # No chain specified as prepared pdb has single A chain
            chain=None,
            directory=str(result_dir),
            # Do not write any fitted models during powerfit run,
            # to spare disk space and time,
            # use `protein-detective powerfit fit-models` command to generate fitted model PDB files
            num=0,
            gpu=gpu,
            nproc=options.nproc,
            delimiter=",",
            progress=progress,  # type: ignore[bad-argument-type]
        )


class FitActor:
    def __init__(self, options: PowerfitOptions):
        logger.info(f"Initializing FitActor with: {options}")
        self.options = options
        self.queue = None
        if options.gpu:
            # Dask worker can only access its assigned GPU, so we can hardcode '0:0'
            self.queue = get_gpu_queue("0:0")
        with options.target.open("rb") as f:
            self.target = setup_target(
                f,
                options.resolution,
                options.no_resampling,
                options.resampling_rate,
                options.no_trimming,
                options.trimming_cutoff,
            )
        self.rotmat = setup_rotational_matrix(options.angle)
        self.fitter: PowerFitter | None = None

    def fit_structure(self, template_structure: Path):
        with template_structure.open("rb") as f:
            template_vars = setup_template_structure(
                f, None, self.target, self.options.resolution, self.options.core_weighted
            )
        _, template, mask, z_sigma = template_vars
        if self.fitter is None:
            self.fitter = PowerFitter(
                self.target, self.rotmat, template, mask, self.queue, self.options.nproc, laplace=self.options.laplace
            )
        else:
            self.fitter.set_template(template, mask)

        self.fitter.scan(progress=None)
        lcc = self.fitter.lcc
        rot = self.fitter.rot
        analysis = Analyzer(
            lcc,
            self.rotmat,
            rot,
            voxelspacing=self.target.voxelspacing,
            origin=self.target.origin,
            z_sigma=z_sigma,
        )
        return template_structure, analysis.solutions
