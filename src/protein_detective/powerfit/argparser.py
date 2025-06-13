from argparse import ArgumentParser, FileType, Namespace
from dataclasses import dataclass
from io import BufferedReader
from pathlib import Path
from shlex import join

from powerfit_em.powerfit import make_parser

# Copy of
# https://github.com/haddocking/powerfit/blob/092c5bc387ad90d046601afa9fe79f4fb67f7408/src/powerfit_em/powerfit.py#L31-L164
# with slight modifications to fit the protein_detective requirements.


def add_powerfit_cli_parser(p: ArgumentParser):
    borrowed_arguments = {
        "target",
        "resolution",
        "angle",
        "laplace",
        "core_weighted",
        "no_resampling",
        "resampling_rate",
        "no_trimming",
        "trimming_cutoff",
        "num",
        "nproc",
    }
    powerfit_parser = make_parser()

    for powerfit_argument in powerfit_parser._actions:
        if powerfit_argument.dest in borrowed_arguments:
            p._add_action(powerfit_argument)

    # Replaces template argument
    p.add_argument("session_dir", help="Session directory for input and output")

    # Removed --chain, as protein-detective created single chain PDB files
    # Removed --directory argument as protein_detective will generate that argument

    # Replaces --gpu, from [<platform>:<device>] to boolean flag
    # When enabled and machine has multiple GPUs, then cycles through them
    p.add_argument(
        "-g",
        "--gpu",
        dest="gpu",
        action="store_true",
        help="Off-load the intensive calculations to the GPU. ",
    )

    p.add_argument(
        "--output",
        dest="output",
        type=FileType("w", encoding="UTF-8"),
        default="-",
        help="Output file for powerfit commands. If set to '-' (default) will print to stdout.",
    )


@dataclass
class PowerfitOptions:
    target: Path
    resolution: float
    angle: float
    laplace: bool
    core_weighted: bool
    no_resampling: bool
    resampling_rate: float
    no_trimming: bool
    trimming_cutoff: float | None
    num: int
    gpu: bool
    nproc: int

    @staticmethod
    def from_args(parsed_args: Namespace) -> "PowerfitOptions":
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
            num=parsed_args.num,
            gpu=parsed_args.gpu,
            nproc=parsed_args.nproc,
        )

    def to_command(self, density_map: Path, template: Path, out_dir: Path, powerfit_cmd: str = "powerfit") -> str:
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
            str(self.num),
            "--gpu" if self.gpu else "",
            "--nproc",
            str(self.nproc),
            "--directory",
            str(out_dir.absolute()),
        ]
        if self.angle:
            args.extend(["--angle", str(self.angle)])
        if self.trimming_cutoff is not None:
            args.extend(["--trimming-cutoff", str(self.trimming_cutoff)])
        # Filter out empty strings
        args = [arg for arg in args if arg]
        return join(args)
