from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter, validators
from cyclopts.types import PositiveFloat, StdioPath

from protein_detective.common_cli import Common, rprint
from protein_detective.powerfit.options import PowerfitOptions, process_group
from protein_detective.powerfit.workflow import powerfit_commands, powerfit_runs

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
        scheduler_address: Address of the Dask scheduler to use. If not provided, will create a local Dask cluster.
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