import logging
from pathlib import Path
from typing import BinaryIO

from powerfit_em.powerfit import powerfit

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

    with structure.open() as template_structure:
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
        )
