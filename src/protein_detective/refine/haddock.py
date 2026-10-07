"""Prepare structures, configure workflows and execute HADDOCK3 refinement."""

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
        rigidbody_sampling: Number of rigidbody samples.
        top_clusters: Number of top clusters to keep.
        top_models: Number of top models to keep.
        water_refinement_sampling_factor: Factor for determining the number of water refinement samples.
        water_refinement_solvent: Solvent used for water refinement.
        ncores: Number of CPU cores to use for a single fitted structure.
            Use a large number such as 9999 to use all available CPU cores.
    """

    rigidbody_sampling: PositiveInt = 1000
    top_clusters: PositiveInt = 10
    top_models: PositiveInt = 2
    water_refinement_sampling_factor: PositiveInt = 1
    water_refinement_solvent: Literal["water", "dmso", "none"] = "none"
    ncores: PositiveInt = 1


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


def run_haddock3(config_file: Path) -> None:
    """Execute a HADDOCK3 workflow and clean its intermediate output.

    Args:
        config_file: Configuration file describing the workflow and output directory.
    """
    modules_params, general_params = setup_run(config_file)
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
