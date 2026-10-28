"""Fixed-coordinate rescoring and metadata joins use the saved source map."""

import csv
import gzip
import shlex
from pathlib import Path

import duckdb
import numpy as np
import pytest
from powerfit_em import Structure, Volume, structure_to_shape_like
from rocrate.model.contextentity import ContextEntity
from rocrate.rocrate import ROCrate

from protein_detective.meta import execute_ddl_statements, refinements_powerfit_rescores_as_duckdb_ddl
from protein_detective.refine.powerfit import rescore_refinement


@pytest.mark.parametrize(
    "scoring_options", [[], ["--no-laplace", "--no-core-weighted", "--no-resampling", "--no-trimming"]]
)
def test_rescore_refinement(tmp_path: Path, scoring_options: list[str]):
    session = tmp_path / "relocated session"
    run = session / "powerfit/source"
    fitted = run / "candidate/fit_1.pdb"
    fitted.parent.mkdir(parents=True)
    fitted.write_text(
        "ATOM      1  N   MET A   1      25.250  30.500  35.750  1.00 20.00           N  \n"
        "ATOM      2  CA  MET A   1      28.000  28.000  37.000  1.00 20.00           C  \n"
        "ATOM      3  C   MET A   1      26.000  32.000  38.000  1.00 20.00           C  \n"
        "ATOM      4  O   MET A   1      24.000  29.000  39.000  1.00 20.00           O  \n"
    )
    structure = Structure.fromfile(str(fitted))
    target = Volume(np.zeros((64, 60, 56)))
    target.array = structure_to_shape_like(target, structure.coor, resolution=8, weights=structure.atomnumber).array
    target.array += np.random.default_rng(123).random(target.shape) * 0.0001
    target.tofile(run / "map.mrc")
    crate = ROCrate()
    density = crate.add_file(
        run / "map.mrc",
        dest_path="powerfit/source/map.mrc",
        properties={"description": "Density map used for fitting."},
    )
    result = crate.add_dataset(run, dest_path="powerfit/source")
    # Historical paths need not exist, and options can precede the positional arguments.
    command = shlex.join(
        [
            "protein-detective",
            "powerfit",
            "run",
            *scoring_options,
            "old map.mrc",
            "8",
            "old session",
            "--powerfit-run-id=source",
        ]
    )
    crate.add(
        ContextEntity(crate, command, properties={"@type": "CreateAction", "object": [density], "result": [result]})
    )
    crate.write(session)
    model_run = session / "refine/refinement/source/candidate/fit_1.pdb"
    output = model_run / "refinement/9_reconstruct"
    output.mkdir(parents=True)
    with gzip.open(output / "same.pdb.gz", "wt") as stream:
        stream.write(fitted.read_text())
    with gzip.open(output / "moved.pdb.gz", "wt") as stream:
        stream.write(
            fitted.read_text()
            .replace("  25.250", "  45.250")
            .replace("  28.000", "  48.000")
            .replace("  26.000", "  46.000")
            .replace("  24.000", "  44.000")
        )
    (output / "io.csv").write_text(
        "model,refined_fitted_structure\n"
        "../6_mdref/same.pdb,9_reconstruct/same.pdb.gz\n"
        "../6_mdref/moved.pdb,9_reconstruct/moved.pdb.gz\n"
    )

    csv_path = rescore_refinement(session, fitted, model_run)

    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    for metric in ("cc", "fishz", "relative_z"):
        assert rows[0][f"before_{metric}"] == rows[0][f"after_{metric}"]
        assert rows[0][f"before_{metric}"] == rows[1][f"before_{metric}"]
        assert float(rows[1][f"after_{metric}"]) < float(rows[1][f"before_{metric}"])
    with duckdb.connect() as con:
        execute_ddl_statements(con, refinements_powerfit_rescores_as_duckdb_ddl(session))
        saved = con.execute(
            "SELECT refine_run_dir, model, before_cc, after_cc FROM refinements_powerfit_rescores ORDER BY model"
        ).fetchall()
    assert len(saved) == 2
    assert saved[0][:2] == (str(model_run.relative_to(session)), "../6_mdref/moved.pdb")
    assert saved[0][2:] == (float(rows[1]["before_cc"]), float(rows[1]["after_cc"]))


def test_rescore_requires_source_provenance(tmp_path: Path):
    with pytest.raises(ValueError, match="missing recorded PowerFit target"):
        rescore_refinement(tmp_path, tmp_path / "powerfit/missing/candidate/fit_1.pdb", tmp_path / "refine")


def test_load_rescores_without_reconstruction_index(tmp_path: Path):
    model_run = tmp_path / "refine/refinement/source/candidate/fit_1.pdb"
    model_run.mkdir(parents=True)
    # A reconstruction without scores must not prevent loading the available CSVs.
    reconstruction = model_run.with_name("fit_2.pdb") / "refinement/9_reconstruct"
    reconstruction.mkdir(parents=True)
    (reconstruction / "io.csv").write_text("model,refined_fitted_structure\n")
    assert refinements_powerfit_rescores_as_duckdb_ddl(tmp_path) == []
    (model_run / "powerfit-recscores.csv").write_text("model,before_cc,after_cc\n../6_mdref/model.pdb,0.5,0.6\n")

    with duckdb.connect() as con:
        execute_ddl_statements(con, refinements_powerfit_rescores_as_duckdb_ddl(tmp_path))
        saved = con.execute(
            "SELECT refine_run_dir, model, before_cc, after_cc FROM refinements_powerfit_rescores"
        ).fetchall()
    assert saved == [(str(model_run.relative_to(tmp_path)), "../6_mdref/model.pdb", 0.5, 0.6)]
