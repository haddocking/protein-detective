from argparse import Namespace
from collections.abc import Generator
from dataclasses import dataclass
from io import BufferedReader
from pathlib import Path
from shlex import join

# Copy of
# https://github.com/haddocking/powerfit/blob/092c5bc387ad90d046601afa9fe79f4fb67f7408/src/powerfit_em/powerfit.py#L31-L164
# with slight modifications to fit the protein_detective requirements.


@dataclass
class PowerfitOptions:
    """Options for the Powerfit command.

    Parameters:
        target: Path to the density map file.
        resolution: Resolution of the density map.
        angle: Angle for the fitting.
        laplace: Whether to use Laplace smoothing.
        core_weighted: Whether to use core weighted fitting.
        no_resampling: Whether to disable resampling.
        resampling_rate: Rate of resampling.
        no_trimming: Whether to disable trimming .
        trimming_cutoff: Cutoff for trimming.
        gpu: Number of workers per GPU. If > 0 then Powerfit will use GPU acceleration otherwise CPU.
        nproc: Number of processes to use. Ignored if GPU is used.
    """

    target: Path
    resolution: float
    angle: float = 10
    laplace: bool = False
    core_weighted: bool = False
    no_resampling: bool = False
    resampling_rate: float = 2
    no_trimming: bool = False
    trimming_cutoff: float | None = None
    gpu: int = 0
    nproc: int = 1

    @staticmethod
    def from_args(parsed_args: Namespace) -> "PowerfitOptions":
        """Create PowerfitOptions from parsed command line arguments.

        Args:
            parsed_args: Parsed command line arguments.

        Returns:
            PowerfitOptions: An instance of PowerfitOptions populated with the parsed arguments.
        """
        target = parsed_args.target
        if isinstance(target, BufferedReader):
            target = target.name
        return PowerfitOptions(
            target=Path(target),
            resolution=parsed_args.resolution,
            angle=parsed_args.angle,
            laplace=parsed_args.laplace,
            core_weighted=parsed_args.core_weighted,
            no_resampling=parsed_args.no_resampling,
            resampling_rate=parsed_args.resampling_rate,
            no_trimming=parsed_args.no_trimming,
            trimming_cutoff=parsed_args.trimming_cutoff,
            gpu=parsed_args.gpu,
            nproc=parsed_args.nproc,
        )

    def to_command(
        self,
        density_map: Path,
        template: Path,
        out_dir: Path,
        powerfit_cmd: str = "powerfit",
        gpu_cycler: Generator[int] | None = None,
    ) -> str:
        """Generate command from options and given arguments.

        Args:
            density_map: Path to the density map file.
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
            str(self.resolution),
            str(template.absolute()),
            "--laplace" if self.laplace else "",
            "--core-weighted" if self.core_weighted else "",
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
        if self.gpu > 0 and gpu_cycler is not None:
            gpu_id = next(gpu_cycler)
            args.extend(["--gpu", str(gpu_id)])
        if self.angle:
            args.extend(["--angle", str(self.angle)])
        if self.trimming_cutoff is not None:
            args.extend(["--trimming-cutoff", str(self.trimming_cutoff)])
        # Filter out empty strings
        args = [arg for arg in args if arg]
        return join(args)
