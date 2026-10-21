"""Expose commands for running, listing and reporting HADDOCK3 refinements."""

import logging
from pathlib import Path
from typing import Annotated

import duckdb
from cyclopts import App, Group, Parameter, validators
from cyclopts.types import PositiveInt, StdioPath
from protein_quest.cli.common import Common

from protein_detective.meta import refinement_runs_query
from protein_detective.refine.haddock import RefineOptions
from protein_detective.refine.report import refinement_report
from protein_detective.refine.run import refine_with_haddock3

refine_app = App(name="refine", help="HADDOCK3 refinement commands")


@refine_app.command
def run(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    known_structure: Annotated[Path, Parameter(validator=validators.Path(file_okay=True, dir_okay=False, exists=True))],
    /,
    *,
    refine_options: Annotated[RefineOptions, Parameter(name="*", group=Group("Refine options", sort_key=0))]
    | None = None,
    remove_known_chains: Annotated[set[str] | None, Parameter(negative="")] = None,
    refine_run_id: str | None = None,
    powerfit_run_id: str | None = None,
    scheduler_address: str | None = None,
    _: Common | None = None,
):
    """Refine structures fitted with PowerFit against a known structure using HADDOCK3.

    The fitted structures will be refined against the known structure
    using HADDOCK3 rigidbody and molecular dynamics refinement.

    The refined fitted structure and refined known structure
    are reconstructed from the refined complex made by HADDOCK3. The known
    structures original chain identifiers and residue numbers are restored.

    Args:
        session_dir: Session directory containing fitted PowerFit results
        known_structure: Path to the known structure to refine against.
            The known structure should be in the same coordinate system as
            the fitted structures from the session directory.
            The known structure should contain the known structures in the volume.
            Can be a PDB or mmCIF file either gzipped or not.
            It will be copied into session directory and
            converted into a structure file with all chains renamed to **B**.
            It will not be translated or rotated.
        refine_options: Refinement options for HADDOCK3.
        remove_known_chains: Chain identifiers to remove from the given known structure before
            renaming the remaining chains to **B**. For mmCIF inputs, use author chain
            identifiers (auth_asym_id). Use this to omit the fitted counterpart of the
            fitted unknown structure.
            To remove multiple chains, repeat the option:
            `--remove-known-chains A --remove-known-chains C`.
        refine_run_id: Set refinement run ID; defaults to refine_run_NNN.
        powerfit_run_id: ID of the PowerFit run to refine.
            If not provided, all fitted models of all powerfit runs will be refined.
        scheduler_address: Address of the Dask scheduler to connect to.
            If not provided, will create a local cluster.
            If set to `sequential` will run tasks sequentially.
    """
    refine_with_haddock3(
        session_dir,
        known_structure,
        refine_options=refine_options,
        remove_known_chains=remove_known_chains,
        refine_run_id=refine_run_id,
        powerfit_run_id=powerfit_run_id,
        scheduler_address=scheduler_address,
        haddock_log_level=logging.root.level,
    )


@refine_app.command
def list_runs(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    output: StdioPath | None = None,
):
    """List refinement runs and saved known structures from their IO indexes.

    Read command options from RO-Crate and include runs recorded in both sources.

    Args:
        session_dir: Session directory containing refinement runs.
        output: CSV output path; defaults to standard output.
    """
    if output is None:
        output = StdioPath("-")
    query, parameters = refinement_runs_query(session_dir)
    destination = "/dev/stdout" if str(output) == "-" else str(output)
    # COPY destinations cannot be bound parameters; escape the SQL string literal.
    destination = destination.replace("'", "''")
    with duckdb.connect() as con:
        con.execute(
            f"""
            COPY ({query}) TO '{destination}' (FORMAT CSV, HEADER)
            """,
            parameters,
        )


@refine_app.command(help=refinement_report.__doc__)
def report(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    refine_run_id: str | None = None,
    top: PositiveInt = 1,
    no_group_by_structure: Annotated[bool, Parameter(negative="")] = False,
    output: StdioPath | None = None,
):
    """Report the best final members of every cluster for each fitted input.

    Args:
        session_dir: Session directory containing refinement results.
        refine_run_id: Refinement run to select; defaults to all runs.
        top: Number of best members per cluster, or overall when grouping is disabled.
            This does not change the workflow's top_clusters or top_models options.
        no_group_by_structure: Select the best top models overall instead of per
            fitted input and cluster.
        output: CSV output path; defaults to standard output.
    """
    results = refinement_report(session_dir, refine_run_id, top, group_by_structure=not no_group_by_structure)
    results["cluster_id"] = (
        results["cluster_id"].map(lambda cluster_id: f"{cluster_id:.0f}", na_action="ignore").fillna("-")
    )
    if output is None:
        output = StdioPath("-")
    with output.open("wt") as fh:
        results.to_csv(fh, index=False)
