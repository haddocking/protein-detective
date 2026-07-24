import sys
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter, validators
from cyclopts.types import PositiveFloat, StdioPath
from rich.table import Table

from protein_detective.common_cli import Common, rprint
from protein_detective.powerfit.options import PowerfitOptions, process_group
from protein_detective.powerfit.workflow import (
    list_lcc_files,
    powerfit_commands,
    powerfit_filtered_report,
    powerfit_fit_models,
    powerfit_list_runs,
    powerfit_runs,
)

powerfit_app = App(name="powerfit", help="PowerFit related commands")


@powerfit_app.command
def commands(
    target: Annotated[Path, Parameter(validator=validators.Path(file_okay=True, dir_okay=False, exists=True))],
    resolution: PositiveFloat,
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    options: PowerfitOptions | None = None,
    powerfit_run_id: str | None = None,
    output: StdioPath | None = None,
    _: Common | None = None,
):
    """Generate PowerFit commands for structure files in the session directory.

    See `powerfit --help` for more information on the available options.

    Args:
        target: Target density map to fit the model in. Data should either be in CCP4 or MRC format
        resolution: Resolution of map in Angstrom
        session_dir: Session directory for input and output
        options: Powerfit specific options.
        powerfit_run_id: ID of the PowerFit run to use. If not provided, will autoincrement based on existing runs.
        output: Output file path. If not specified, defaults to standard output.
    """
    if options is None:
        options = PowerfitOptions()
    if output is None:
        output = StdioPath("-")

    commands, powerfit_run_id = powerfit_commands(
        target,
        resolution,
        session_dir,
        options=options,
        powerfit_run_id=powerfit_run_id,
    )
    with output.open("wt") as fh:
        print("# Run the commands below in your own way", file=fh)
        print("# When you are done", file=fh)
        print(f"# in {Path().absolute()} directory", file=fh)
        print(
            f"# run `protein-detective powerfit report {session_dir} {powerfit_run_id}` to show best solutions.",
            file=fh,
        )
        for command in commands:
            print(command, file=fh)


@powerfit_app.command
def run(
    target: Annotated[Path, Parameter(validator=validators.Path(file_okay=True, dir_okay=False, exists=True))],
    resolution: PositiveFloat,
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    options: PowerfitOptions | None = None,
    powerfit_run_id: str | None = None,
    scheduler_address: Annotated[str | None, Parameter(group=process_group)] = None,
):
    """Run PowerFit on PDB files in the session directory and store results.

    See `powerfit --help` for more information on the available options.

    Args:
        target: Target density map to fit the model in. Data should either be in CCP4 or MRC format
        resolution: Resolution of map in Angstrom
        session_dir: Session directory for input and output
        options: Powerfit specific options.
        powerfit_run_id: ID of the PowerFit run to use. If not provided, will autoincrement based on existing runs.
        output: Output file path. If not specified, defaults to standard output.
        scheduler_address: Address of the Dask scheduler to use.
            Use `sequential` to run PowerFit sequentially without Dask cluster.
            If not provided, will create a local Dask cluster.
    """
    if options is None:
        options = PowerfitOptions()
    powerfit_runs(
        target,
        resolution,
        session_dir,
        options=options,
        powerfit_run_id=powerfit_run_id,
        scheduler_address=scheduler_address,
    )
    rprint(f"PowerFit run completed with ID: {powerfit_run_id}. Use this ID for reporting or fitting models.")


@powerfit_app.command
def report(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    powerfit_run_id: str | None = None,
    top: int = 1,
    no_group_by_structure: Annotated[bool, Parameter(negative="")] = False,
    output: StdioPath | None = None,
):
    """Generate a report of the best PowerFit solutions.

    Args:
        session_dir: Session directory containing PowerFit results
        powerfit_run_id: ID of the PowerFit run to report on
        top: Number of top solutions to report per structure.
        no_group_by_structure: If absent, group solutions by structure.
            If present, top will be overall instead of per structure.
        output: Output file for solutions table. If set to '-' (default) will print to stdout.
    """
    if output is None:
        output = StdioPath("-")
    group_by_structure = not no_group_by_structure
    solutions = powerfit_filtered_report(
        session_dir,
        powerfit_run_id,
        top,
        group_by_structure=group_by_structure,
    )

    def array_to_str(arr):
        return ":".join(map(str, arr.flatten()))

    # Convert translation and rotation to : delimited string for CSV output
    solutions.loc[:, "translation"] = solutions["translation"].apply(array_to_str)
    solutions.loc[:, "rotation"] = solutions["rotation"].apply(array_to_str)

    if output.is_stdio:
        # Pandas does not like StdioPath
        solutions.to_csv(sys.stdout, index=False)
    else:
        solutions.to_csv(output, index=False)


@powerfit_app.command
def fit_models(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    powerfit_run_id: str | None = None,
    top: int = 1,
    no_group_by_structure: Annotated[bool, Parameter(negative="")] = False,
    output: StdioPath | None = None,
):
    """Fit models to the best PowerFit solutions.

    Args:
        session_dir: Session directory containing PowerFit results
        powerfit_run_id: ID of the PowerFit run to report on
        top: Number of top solutions to fit per structure.
        no_group_by_structure: If absent, group solutions by structure.
            If present, top will be overall instead of per structure.
        output: Output file for fitted models table. If set to '-' (default) will print to stdout.

    """
    if output is None:
        output = StdioPath("-")
    group_by_structure = not no_group_by_structure

    fitted = powerfit_fit_models(session_dir, powerfit_run_id, top, group_by_structure=group_by_structure)
    if output.is_stdio:
        # Pandas does not like StdioPath
        fitted.to_csv(sys.stdout, index=False)
    else:
        fitted.to_csv(output, index=False)


@powerfit_app.command
def list_runs(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
):
    """List all PowerFit runs in the session directory.

    Args:
        session_dir: Directory containing the session data.
    """
    runs = powerfit_list_runs(session_dir)
    if len(runs) == 0:
        rprint("No PowerFit runs found.")
        return

    table = Table(title="PowerFit runs")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("Density map (copy)", style="green")
    table.add_column("Directory", style="magenta")
    for row in runs:
        table.add_row(row[0], row[1], str(row[2]))
    rprint(table)


@powerfit_app.command
def list_lcc(
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
):
    """List Local Cross Validation (lcc.mrc) files for all PowerFit runs.

    Args:
        session_dir: Directory containing the session data.
    """
    lcc_files = list_lcc_files(session_dir)

    if not lcc_files:
        rprint("[yellow]No lcc.mrc files found. Please run at least one powerfit.[/yellow]")
        return

    table = Table(title="PowerFit LCC files")
    table.add_column("Run ID", justify="right", style="cyan")
    table.add_column("Structure", style="magenta")
    table.add_column("LCC file", style="green")
    for run_id, structure, lcc_file in lcc_files:
        table.add_row(run_id, structure, str(lcc_file))
    rprint(table)
