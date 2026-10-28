"""Rescore fitted and refined candidates at their supplied coordinates."""

import argparse
import csv
from dataclasses import fields
from pathlib import Path
from typing import NamedTuple

from powerfit_em import Volume
from powerfit_em.powerfit import add_scoring_arguments2parser
from powerfit_em.score import score_pose, setup_structure_with_laplace, setup_target_with_laplace

from protein_detective.powerfit.options import PowerfitOptions
from protein_detective.powerfit.provenance import powerfit_run_arguments_from_rocrate
from protein_detective.provenance import command_arguments

SCORE_COLUMNS = [f"{stage}_{metric}" for stage in ("before", "after") for metric in ("cc", "fishz", "relative_z")]


class PowerfitScore(NamedTuple):
    """Fixed-coordinate PowerFit scores in CSV column order."""

    cc: float
    fishz: float
    relative_z: float


class RefinementScore(NamedTuple):
    """A refined member's model ID and paired PowerFit scores."""

    model: str
    before: PowerfitScore
    after: PowerfitScore


def _prepare_target(session_dir: Path, fitted_model: Path) -> tuple[Volume, float, argparse.Namespace]:
    """Load the source map using its recorded resolution and scoring options."""
    run_id = fitted_model.relative_to(session_dir / "powerfit").parts[0]
    recorded = powerfit_run_arguments_from_rocrate(session_dir).get(run_id)
    if recorded is None or recorded["used_target"] is None or recorded["options"] is None:
        msg = f"Cannot rescore refinement: missing recorded PowerFit target or arguments for {run_id}"
        raise ValueError(msg)
    arity = {
        "--" + field.name.replace("_", "-"): not isinstance(field.default, bool) for field in fields(PowerfitOptions)
    }
    arity.update({"--powerfit-run-id": True, "--scheduler-address": True})
    arity.update(dict.fromkeys(("--verbose", "--quiet", "-v", "-q"), False))
    parsed = command_arguments("powerfit " + recorded["options"], ("powerfit",), arity)
    if parsed is None or len(parsed[0]) != 3:
        msg = f"Cannot read recorded PowerFit resolution and scoring options for {run_id}"
        raise ValueError(msg)
    resolution = float(parsed[0][1])
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    add_scoring_arguments2parser(parser)
    options, _ = parser.parse_known_args(parsed[1])
    with (session_dir / recorded["used_target"]).open("rb") as stream:
        target = setup_target_with_laplace(
            target_volume=stream,
            resolution=resolution,
            no_resampling=options.no_resampling,
            resampling_rate=options.resampling_rate,
            no_trimming=options.no_trimming,
            trimming_cutoff=options.trimming_cutoff,
            laplace=not options.no_laplace,
        )

    return target, resolution, options


def _score_structure(path: Path, target: Volume, resolution: float, options: argparse.Namespace) -> PowerfitScore:
    """Return CC, Fisher z and relative z for a structure at its saved coordinates."""
    with path.open("rb") as stream:
        structure, mask, z_sigma = setup_structure_with_laplace(
            structure=stream,
            chain=None,
            target=target,
            resolution=resolution,
            core_weighted=not options.no_core_weighted,
            laplace=not options.no_laplace,
        )
    return PowerfitScore(*score_pose(target=target, structure=structure, mask=mask, z_sigma=z_sigma))


def _write_recscores(refine_run_dir: Path, rows: list[RefinementScore]) -> Path:
    """Write model IDs and before/after scores after every structure has been scored."""
    output = refine_run_dir / "powerfit-recscores.csv"
    with output.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["model", *SCORE_COLUMNS])
        writer.writerows((row.model, *row.before, *row.after) for row in rows)
    return output


def rescore_refinement(session_dir: Path, fitted_model: Path, refine_run_dir: Path) -> Path:
    """Write before/after PowerFit scores for every reconstructed refinement member.

    Score the fitted input once and each refined candidate at its saved atomic
    coordinates, reusing the source map, resolution and scoring options recorded
    in the session's RO-Crate. Fixed-coordinate scores can differ from the
    original PowerFit search scores because density and masks are rebuilt.

    Read model IDs and refined candidate paths from refinement/9_reconstruct/io.csv
    under refine_run_dir. Candidate paths are relative to the refinement workflow.
    Write one CSV row per member, repeating the input's before scores alongside
    that member's after scores. Each stage includes CC, Fisher z and relative z.
    Write the output only after all structures have been scored successfully.

    Args:
        session_dir: Absolute session directory containing PowerFit results and RO-Crate metadata.
        fitted_model: Absolute fitted input path under session_dir/powerfit/<run_id>.
        refine_run_dir: Model run directory containing the completed refinement workflow.

    Returns:
        Path to powerfit-recscores.csv in refine_run_dir. An existing file is overwritten.

    Raises:
        ValueError: The fitted input is outside the PowerFit directory, required
            provenance is missing, recorded arguments cannot be read, or a pose
            has zero density variance inside its scoring mask.
        FileNotFoundError: The source map, fitted input, reconstruction index or
            a refined candidate is missing.
    """
    target, resolution, options = _prepare_target(session_dir, fitted_model)
    before = _score_structure(fitted_model, target, resolution, options)
    refinement = refine_run_dir / "refinement"
    with (refinement / "9_reconstruct/io.csv").open() as stream:
        models = list(csv.DictReader(stream))
    rows = [
        RefinementScore(
            model=model["model"],
            before=before,
            after=_score_structure(refinement / model["refined_fitted_structure"], target, resolution, options),
        )
        for model in models
    ]
    return _write_recscores(refine_run_dir, rows)
