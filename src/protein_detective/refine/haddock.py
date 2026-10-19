"""Prepare structures, configure workflows and execute HADDOCK3 refinement."""

import logging
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Literal

from cyclopts.types import PositiveInt
from haddock.core.defaults import RUNDIR
from haddock.gear.prepare_run import setup_run
from haddock.libs.libio import working_directory
from haddock.libs.libworkflow import WorkflowManager
from protein_quest.structure.chains import chains_in_structure
from protein_quest.structure.formats import read_structure, write_structure


@dataclass
class RefineOptions:
    """Options for refining a structure with HADDOCK3.

    Attributes:
        ncores: Number of CPU cores to use for a single fitted structure.
            Use a large number such as 9999 to use all available CPU cores.
        rigidbody_sampling: Number of rigidbody samples.
        top_clusters: Number of top clusters to keep.
        top_models: Number of top models to keep.
        water_refinement_sampling_factor: Factor for determining the number of water refinement samples.
        water_refinement_solvent: Solvent used for water refinement.
        fcc_clust_cutoff: Minimum fraction of common contacts (FCC) to be considered in a cluster.
    """

    ncores: PositiveInt = 1
    rigidbody_sampling: PositiveInt = 1000
    top_clusters: PositiveInt = 10
    top_models: PositiveInt = 2
    water_refinement_sampling_factor: PositiveInt = 1
    water_refinement_solvent: Literal["water", "dmso", "none"] = "none"
    fcc_clust_cutoff: float = 0.60


def prepare_fitted_and_fixed(fitted_model: Path, fixed_structure: Path, output_dir: Path) -> Path:
    """Combine fitted chain A and fixed chain B without transforming coordinates.

    Args:
        fitted_model: Fitted structure containing only chain A.
        fixed_structure: Prepared fixed structure containing only chain B.
        output_dir: Directory in which to write the combined structure.

    Returns:
        Path to fitted-and-fixed.pdb.

    Raises:
        ValueError: An input has multiple models or unexpected chains.
    """
    structure = read_structure(fitted_model)
    fixed = read_structure(fixed_structure)
    if len(structure) != 1 or len(fixed) != 1:
        msg = "Baseline scoring requires single-model fitted and fixed structures."
        raise ValueError(msg)
    if [chain.name for chain in structure[0]] != ["A"]:
        msg = "Fitted structure must contain only chain A."
        raise ValueError(msg)
    if [chain.name for chain in fixed[0]] != ["B"]:
        msg = "Fixed structure must contain only chain B."
        raise ValueError(msg)
    structure[0].add_chain(fixed[0]["B"].clone())
    output = output_dir / "fitted-and-fixed.pdb"
    write_structure(structure, output)
    return output


def generate_unrefined_config_body(run_dir: Path, complex_file: Path, ncores: int) -> str:
    """Configure the separate energy-minimized fitted-structure baseline.

    Args:
        run_dir: HADDOCK3 scoring output directory.
        complex_file: Combined fitted and fixed structure file.
        ncores: Number of CPU cores to use.

    Returns:
        HADDOCK3 configuration text for baseline scoring.
    """
    return dedent(f"""\
        run_dir = "{run_dir}"
        mode = "local"
        ncores = {ncores}
        clean = true
        postprocess = true

        molecules = ["{complex_file}"]

        [topoaa]

        [emscoring]

        [caprieval]
        """)


def generate_haddock3_config_body(
    run_dir: Path, fitted_model: Path, fixed_structure: Path, options: RefineOptions
) -> str:
    """Generate the configuration body for a HADDOCK3 refinement run.

    Args:
        run_dir: Path of the HADDOCK3 run directory.
        fitted_model: Path to the fitted model file.
        fixed_structure: Path to the fixed structure file.
        options: Refinement parameters for HADDOCK3.

    Returns:
        HADDOCK3 configuration text for the refinement run.
    """
    return dedent(f"""\
        run_dir = "{run_dir}"
        mode = "local"
        ncores = {options.ncores}
        clean = true
        postprocess = true

        molecules = [
            "{fitted_model}",
            "{fixed_structure}"
        ]

        [topoaa]

        [rigidbody]
        separate = false
        mol_fix_origin_2 = true
        sampling = {options.rigidbody_sampling}
        cmrest = true

        [caprieval]

        [clustfcc]
        min_population = 1

        [caprieval]

        [seletopclusts]
        top_clusters = {options.top_clusters}
        top_models = {options.top_models}

        [mdref]
        sampling_factor = {options.water_refinement_sampling_factor}
        solvent = "{options.water_refinement_solvent}"

        [clustfcc]
        min_population = 1
        clust_cutoff = {options.fcc_clust_cutoff}

        [caprieval]
        """)


def prepare_fixed_structure(
    fixed_structure: Path, refine_dir: Path, out_chain: str = "B", *, remove_fixed_chains: set[str] | None = None
) -> Path:
    """Prepare the fixed structure for refinement.

    By removing selected chains, converting it to PDB format and renaming chains if necessary.

    Args:
        fixed_structure: Path to the fixed structure file.
        refine_dir: Directory where the refined structure will be saved.
        out_chain: The chain identifier to rename to if necessary.
        remove_fixed_chains: Original chain identifiers to remove from every model before renaming.
            For mmCIF inputs, use author chain identifiers (auth_asym_id).

    Returns:
        Path to the prepared fixed structure in PDB format.

    Raises:
        ValueError: A requested chain is missing or all chains would be removed.
    """
    fixed_structure_dest = refine_dir / "fixed_structure.pdb"
    structure = read_structure(fixed_structure)

    if remove_fixed_chains:
        chains_to_remove = remove_fixed_chains
        chain_names = {chain.name for chain in chains_in_structure(structure)}
        missing_chains = chains_to_remove - chain_names
        if missing_chains:
            msg = f"Chains not found in fixed structure: {', '.join(sorted(missing_chains))}"
            raise ValueError(msg)
        if not chain_names - chains_to_remove:
            msg = "Cannot remove all chains from the fixed structure."
            raise ValueError(msg)
        for model in structure:
            for chain_name in chains_to_remove:
                model.remove_chain(chain_name)

    chain_names = {chain.name for chain in chains_in_structure(structure)}
    for chain_name in chain_names - {out_chain}:
        structure.rename_chain(chain_name, out_chain)

    write_structure(structure, fixed_structure_dest)
    return fixed_structure_dest


def set_haddock3_log_level(log_level: int) -> None:
    """Set the level of the HADDOCK3 logger and its own console handler.

    HADDOCK3 logs through its own stdout handler at INFO level, so the root logger level does not apply.
    Propagation to the root logger is disabled to avoid printing each message twice.

    Args:
        log_level: Logging level, for example `logging.WARNING`.
    """
    haddock_logger = logging.getLogger("haddock")
    haddock_logger.setLevel(log_level)
    for handler in haddock_logger.handlers:
        handler.setLevel(log_level)
    haddock_logger.propagate = False


def run_haddock3(config_file: Path, log_level: int = logging.INFO) -> None:
    """Execute a HADDOCK3 workflow, do postprocessing and clean its intermediate output.

    Args:
        config_file: Configuration file describing the workflow and output directory.
        log_level: Logging level of HADDOCK3 messages.
    """
    set_haddock3_log_level(log_level)
    # Start at step zero to allow the config and inputs inside same existing directory as output.
    modules_params, general_params = setup_run(config_file, restart_from=0)
    run_dir = general_params[RUNDIR]

    with working_directory(run_dir):
        workflow = WorkflowManager(
            workflow_params=modules_params,
            start=None,
            **general_params,
        )
        workflow.run()

        if general_params.get("postprocess", True):
            workflow.postprocess(self_contained=general_params.get("gen_archive", False))

        workflow.clean()
