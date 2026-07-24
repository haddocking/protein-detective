from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from shlex import join
from typing import Annotated, Literal, get_args

from cyclopts import Group, Parameter
from cyclopts.types import PositiveFloat, PositiveInt
from powerfit_em.correlators.shared import DEFAULT_BATCH_SIZE

type GpuBackend = Literal["opencl", "cuda"]
gpu_backends: tuple[GpuBackend, ...] = get_args(GpuBackend.__value__)


def parse_first_visible_gpu_id(visible_devices: str | None) -> int:
    """Parse first GPU id from visible-devices env var value.

    Falls back to GPU 0 when the value is missing, empty, or invalid.
    """
    if not visible_devices:
        return 0
    first_visible_device = visible_devices.split(",")[0].strip()
    if not first_visible_device:
        return 0
    try:
        return int(first_visible_device)
    except ValueError:
        return 0


powerfit_group = Group.create_ordered("PowerFit specific parameters")
process_group = Group.create_ordered("Process parameters")


# Copy of
# https://github.com/haddocking/powerfit/blob/092c5bc387ad90d046601afa9fe79f4fb67f7408/src/powerfit_em/powerfit.py#L31-L164
# with slight modifications to fit the protein_detective requirements.
@Parameter(name="*", group=powerfit_group)
@dataclass
class PowerfitOptions:
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
        gpu: Off-load the intensive calculations to the GPU. Otherwise uses CPU.
        workers_per_gpu: Number of workers to run per GPU.
        gpu_backend: Backend to use for GPU processing.
        nproc: Number of processors used during search.
            The number will be capped at the total number
            of available processors on your machine.
        batch_size: GPU batch size to use.
            Use 0 to disable batching entirely, or a positive integer to force a specific batch size.
            Applies to GPU backends (CUDA/OpenCL).
            If set too high will cause out-of-memory errors.
    """

    angle: PositiveFloat = 10.0
    no_laplace: Annotated[bool, Parameter(negative="")] = False
    no_core_weighted: Annotated[bool, Parameter(negative="")] = False
    no_resampling: Annotated[bool, Parameter(negative="")] = False
    resampling_rate: PositiveFloat = 2.0
    no_trimming: Annotated[bool, Parameter(negative="")] = False
    trimming_cutoff: PositiveFloat | None = None
    gpu: Annotated[bool, Parameter(group=process_group, negative="")] = True
    workers_per_gpu: Annotated[PositiveInt, Parameter(group=process_group)] = 1
    gpu_backend: Annotated[GpuBackend, Parameter(group=process_group)] = "opencl"
    nproc: Annotated[PositiveInt, Parameter(group=process_group)] = 1
    batch_size: Annotated[PositiveInt, Parameter(group=process_group)] = DEFAULT_BATCH_SIZE

    def format_gpu_device(self, gpu_id: int) -> str:
        if self.gpu_backend == "cuda":
            return f"cuda:{gpu_id}"
        return f"0:{gpu_id}"

    def to_command(
        self,
        density_map: Path,
        resolution: float,
        template: Path,
        out_dir: Path,
        powerfit_cmd: str = "powerfit",
        gpu_cycler: Generator[int] | None = None,
    ) -> str:
        """Generate command from options and given arguments.

        Args:
            density_map: Path to the density map file.
            resolution: Resolution of the density map in Angstroms.
            template: Path to the template PDB file.
            out_dir: Directory to save the output files.
            powerfit_cmd: Command to run Powerfit (default is "powerfit").
            gpu_cycler: Generator to cycle through GPU indices.

        Returns:
            A string representing the command to run Powerfit.
        """
        args = [
            powerfit_cmd,
            str(density_map.absolute()),
            str(resolution),
            str(template.absolute()),
            "--no-laplace" if self.no_laplace else "",
            "--no-core-weighted" if self.no_core_weighted else "",
            "--no-resampling" if self.no_resampling else "",
            "--resampling-rate",
            str(self.resampling_rate),
            "--no-trimming" if self.no_trimming else "",
            "--num",
            # Do not write any fitted models during powerfit run,
            # to spare disk space and time,
            # use `protein-detective powerfit fit-models` command to generate fitted model PDB files
            str(0),
            "--nproc",
            str(self.nproc),
            "--directory",
            str(out_dir.absolute()),
            "--delimiter",
            ",",
        ]
        if self.gpu and gpu_cycler is not None:
            gpu_id = next(gpu_cycler)
            args.extend(["--gpu", self.format_gpu_device(gpu_id)])
        if self.batch_size != DEFAULT_BATCH_SIZE:
            args.extend(["--batch-size", str(self.batch_size)])
        if self.angle:
            args.extend(["--angle", str(self.angle)])
        if self.trimming_cutoff is not None:
            args.extend(["--trimming-cutoff", str(self.trimming_cutoff)])
        # Filter out empty strings
        args = [arg for arg in args if arg]
        return join(args)
