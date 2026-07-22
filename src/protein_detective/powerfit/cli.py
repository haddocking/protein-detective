from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from cyclopts import App, Group, Parameter, validators
from cyclopts.types import PositiveFloat, PositiveInt, StdioPath
from powerfit_em.correlators.shared import DEFAULT_BATCH_SIZE

from protein_detective.powerfit.options import GpuBackend

powerfit_app = App(name="powerfit", help="PowerFit related commands")

powerfit_group = Group.create_ordered("PowerFit specific parameters")
process_group = Group.create_ordered("Process parameters")


@Parameter(name="*", group=process_group)
@dataclass
class ProcessOptions:
    """Process related options.

    Attributes:
        gpu: Off-load the intensive calculations to the GPU.
        gpu_backend: Backend to use for GPU processing.
        nproc: Number of processors used during search.
            The number will be capped at the total number
            of available processors on your machine.
        batch_size: GPU batch size to use.
            Use 0 to disable batching entirely, or a positive integer to force a specific batch size.
            Applies to GPU backends (CUDA/OpenCL).
            If set too high will cause out-of-memory errors.
    """

    gpu: bool = False
    gpu_backend: GpuBackend = "opencl"
    nproc: PositiveInt = 1
    batch_size: PositiveInt = DEFAULT_BATCH_SIZE


@Parameter(name="*", group=powerfit_group)
@dataclass
class PowerfitSpecificOptions:
    """PowerFit specific options.

    Attributes:
        angle: Rotational sampling density in degree. Increasing
            this number by a factor of 2 results in approximately
            8 times more rotations sampled.
        no_laplace: Do not use the Laplace pre-filter density data.
        no_core_weighted: Do not use core-weighted local cross-correlation score.
        no_resampling: Do not resample the density map.
        resampling_rate: Resampling rate compared to Nyquist.
        no_trimming: Do not trim the density map.
        trimming_cutoff: Intensity cutoff to which the map will be trimmed. Default is 10 percent of maximum intensity.
    """

    angle: PositiveFloat = 10.0
    no_laplace: Annotated[bool, Parameter(negative="")] = False
    no_core_weighted: Annotated[bool, Parameter(negative="")] = False
    no_resampling: Annotated[bool, Parameter(negative="")] = False
    resampling_rate: PositiveFloat = 2.0
    no_trimming: Annotated[bool, Parameter(negative="")] = False
    trimming_cutoff: PositiveFloat | None = None


@powerfit_app.command
def commands(
    target: Annotated[Path, Parameter(validator=validators.Path(file_okay=True, dir_okay=False, exists=True))],
    resolution: PositiveFloat,
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    /,
    *,
    powerfit_specific_options: PowerfitSpecificOptions | None = None,
    process_options: ProcessOptions | None = None,
    output: StdioPath | None = None,
    powerfit_run_id: str | None = None,
):
    """Generate PowerFit commands for structure files in the session directory.

    See `powerfit --help` for more information on the available options.

    Args:
        target: Target density map to fit the model in. Data should either be in CCP4 or MRC format
        resolution: Resolution of map in Angstrom
        session_dir: Session directory for input and output
        powerfit_specific_options: Powerfit specific options.
        process_options: Process related options.
        output: Output file path. If not specified, defaults to standard output.
        powerfit_run_id: ID of the PowerFit run to use. If not provided, will autoincrement based on existing runs.
    """
    if powerfit_specific_options is None:
        powerfit_specific_options = PowerfitSpecificOptions()
    if process_options is None:
        process_options = ProcessOptions()
    if output is None:
        output = StdioPath("-")
