from argparse import ArgumentParser, FileType, Namespace
from dataclasses import dataclass
from pathlib import Path
from shlex import join

# Copy of
# https://github.com/haddocking/powerfit/blob/092c5bc387ad90d046601afa9fe79f4fb67f7408/src/powerfit_em/powerfit.py#L31-L164
# with slight modifications to fit the protein_detective requirements.
# TODO expose parser object in powerfit module


def add_powerfit_cli_parser(p: ArgumentParser):
    # Positional arguments
    p.add_argument(
        "target",
        type=str,
        help="Target density map to fit the model in. Data should either be in CCP4 or MRC format",
    )
    p.add_argument("resolution", type=float, help="Resolution of map in angstrom")

    # Replaces template argument
    p.add_argument("session_dir", help="Session directory for input and output")

    # Optional arguments and flags
    p.add_argument(
        "-a",
        "--angle",
        dest="angle",
        type=float,
        default=10,
        metavar="<float>",
        help="Rotational sampling density in degree. Increasing "
        "this number by a factor of 2 results in approximately "
        "8 times more rotations sampled.",
    )
    # Scoring flags
    p.add_argument(
        "-l",
        "--laplace",
        dest="laplace",
        action="store_true",
        help="Use the Laplace pre-filter density data. Can be combined with the core-weighted local cross-correlation.",
    )
    p.add_argument(
        "-cw",
        "--core-weighted",
        dest="core_weighted",
        action="store_true",
        help="Use core-weighted local cross-correlation score. Can be combined with the Laplace pre-filter.",
    )
    # Resampling
    p.add_argument(
        "-nr",
        "--no-resampling",
        dest="no_resampling",
        action="store_true",
        help="Do not resample the density map.",
    )
    p.add_argument(
        "-rr",
        "--resampling-rate",
        dest="resampling_rate",
        type=float,
        default=2,
        metavar="<float>",
        help="Resampling rate compared to Nyquist.",
    )
    # Trimming related
    p.add_argument(
        "-nt",
        "--no-trimming",
        dest="no_trimming",
        action="store_true",
        help="Do not trim the density map.",
    )
    p.add_argument(
        "-tc",
        "--trimming-cutoff",
        dest="trimming_cutoff",
        type=float,
        default=None,
        metavar="<float>",
        help="Intensity cutoff to which the map will be trimmed. Default is 10 percent of maximum intensity.",
    )
    # Selection parameter
    # Removed --chain, as protein-detective created single chain PDB files
    # Output parameters
    # Removed --directory argument as protein_detective will generate that argument
    p.add_argument(
        "-n",
        "--num",
        dest="num",
        type=int,
        default=10,
        metavar="<int>",
        help="Number of models written to file. This number will be capped if less solutions are found as requested.",
    )
    # Computational resources parameters
    p.add_argument(
        "-g",
        "--gpu",
        dest="gpu",
        action="store_true",
        help="Off-load the intensive calculations to the GPU. ",
    )
    p.add_argument(
        "-p",
        "--nproc",
        dest="nproc",
        type=int,
        default=1,
        metavar="<int>",
        help="Number of processors used during search. "
        "The number will be capped at the total number "
        "of available processors on your machine.",
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
    session_dir: Path
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
        return PowerfitOptions(
            target=Path(parsed_args.target),
            resolution=parsed_args.resolution,
            session_dir=Path(parsed_args.session_dir),
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
            str(self.angle),
            "--laplace" if self.laplace else "",
            "--core-weighted" if self.core_weighted else "",
            "--no-resampling" if self.no_resampling else "",
            str(self.resampling_rate),
            "--no-trimming" if self.no_trimming else "",
            str(self.trimming_cutoff) if self.trimming_cutoff is not None else "",
            str(self.num),
            "--gpu" if self.gpu else "",
            str(self.nproc),
            "--directory",
            str(out_dir.absolute()),
        ]
        # Filter out empty strings
        args = [arg for arg in args if arg]
        return join(args)
