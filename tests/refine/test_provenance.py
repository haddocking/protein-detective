import getpass
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path

from rocrate.metadata import BASENAME

from protein_detective.__version__ import __version__
from protein_detective.refine.haddock import (
    RefineOptions,
    generate_haddock3_config_body,
    generate_unrefined_config_body,
)
from protein_detective.refine.provenance import refine_run_arguments_from_rocrate, write_refinement_ro_crate
from protein_detective.refine.run import create_refinement_run
from tests.helpers import cli_args


def test_recorded_refinement_arguments_and_fixed_structure_origin(session_with_powerfit_results: Path, tmp_path: Path):
    assert refine_run_arguments_from_rocrate(session_with_powerfit_results) == {}

    run_dir = create_refinement_run(session_with_powerfit_results)
    original = tmp_path / "original fixed.pdb"
    original.write_text("END\n")
    fixed_structure = run_dir / "fixed_structure.pdb"
    fixed_structure.write_text("END\n")
    fitted = session_with_powerfit_results / "powerfit/run_001/same_structure/fit_1.pdb"
    refinement_run = run_dir / "run_001/same_structure/fit_1.pdb"
    refinement_run.mkdir(parents=True)
    (refinement_run / "refinement").mkdir()
    baseline = refinement_run / "baseline"
    baseline.mkdir()
    complex_file = baseline / "fitted-and-fixed.pdb"
    complex_file.write_text("END\n")
    (baseline / "workflow.cfg").write_text(generate_unrefined_config_body(baseline, complex_file, 1))
    options = RefineOptions(rigidbody_sampling=10)
    (refinement_run / "refinement/workflow.cfg").write_text(
        generate_haddock3_config_body(
            run_dir=refinement_run / "refinement", fitted_model=fitted, fixed_structure=fixed_structure, options=options
        )
    )
    io_csv = run_dir / "io.csv"
    io_csv.write_text(
        "refine_run_id,powerfit_run_id,fitted_model,refine_run_dir\n"
        f"{run_dir.name},run_001,{fitted.relative_to(session_with_powerfit_results)},{refinement_run.relative_to(session_with_powerfit_results)}\n"
    )

    invocation_options = [
        "--rigidbody-sampling",
        "10",
        "--remove-fixed-chains",
        "A",
        "--powerfit-run-id",
        "run_001",
    ]
    start_time = datetime(2026, 10, 19, tzinfo=UTC)
    with cli_args(["refine", "run", str(session_with_powerfit_results), str(original), *invocation_options]):
        write_refinement_ro_crate(
            session_dir=session_with_powerfit_results,
            start_time=start_time,
            session_fixed_structure=fixed_structure,
            fixed_structure=original,
            refined=[(fitted, refinement_run)],
            io_csv=io_csv,
            options=options,
            remove_fixed_chains={"A"},
            powerfit_run_id="run_001",
        )

    assert refine_run_arguments_from_rocrate(session_with_powerfit_results) == {
        run_dir.name: (str(original), shlex.join(invocation_options)),
    }

    command = shlex.join(
        ["protein-detective", "refine", "run", str(session_with_powerfit_results), str(original), *invocation_options]
    )
    crate_bytes = (session_with_powerfit_results / BASENAME).read_bytes()
    metadata = json.loads(crate_bytes)
    action = next(item for item in metadata["@graph"] if item["@id"] == command)
    end_time = action["endTime"]
    pwd_id = action["environment"][0]["@id"]
    expected = {
        "@context": ["https://w3id.org/ro/crate/1.1/context", "https://w3id.org/ro/terms/workflow-run/context"],
        "@graph": [
            {
                "@id": "./",
                "@type": "Dataset",
                "conformsTo": {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
                "datePublished": end_time,
                "description": "An RO-Crate recording the files and directories that were used as input or "
                "output by protein-detective.",
                "hasPart": [
                    {"@id": "refine/refine_run_001/fixed_structure.pdb"},
                    {"@id": "powerfit/run_001/same_structure/fit_1.pdb"},
                    {"@id": "refine/refine_run_001/io.csv"},
                    {"@id": "refine/refine_run_001/run_001/same_structure/fit_1.pdb/"},
                ],
                "license": "CC-BY-4.0",
                "name": "Files used by protein-detective",
            },
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "about": {"@id": "./"},
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            },
            {
                "@id": "https://w3id.org/ro/wfrun/process/0.5",
                "@type": "CreativeWork",
                "name": "Process Run Crate",
                "version": "0.5",
            },
            {
                "@id": f"protein-detective@{__version__}",
                "@type": "SoftwareApplication",
                "description": "Detect proteins in EM density map",
                "name": "protein-detective",
                "version": __version__,
            },
            {
                "@id": "refine/refine_run_001/fixed_structure.pdb",
                "@type": "File",
                "contentSize": 4,
                "description": (
                    f"Fixed structure prepared from {original.resolve()}; "
                    "removed chains ['A']; renamed remaining chains to B."
                ),
                "encodingFormat": "chemical/x-pdb",
                "name": "refine/refine_run_001/fixed_structure.pdb",
            },
            {
                "@id": "powerfit/run_001/same_structure/fit_1.pdb",
                "@type": "File",
                "contentSize": 13,
                "description": "Fitted model file.",
                "encodingFormat": "chemical/x-pdb",
                "name": "powerfit/run_001/same_structure/fit_1.pdb",
            },
            {
                "@id": "refine/refine_run_001/io.csv",
                "@type": "File",
                "contentSize": 178,
                "description": "CSV file containing fitted model path and refine run dir.",
                "encodingFormat": "text/csv",
                "name": "refine/refine_run_001/io.csv",
            },
            {
                "@id": "refine/refine_run_001/run_001/same_structure/fit_1.pdb/",
                "@type": "Dataset",
                "description": "Baseline and refinement haddock3 results.",
                "name": "refine/refine_run_001/run_001/same_structure/fit_1.pdb",
            },
            {"@id": getpass.getuser(), "@type": "Person", "name": getpass.getuser()},
            {
                "@id": command,
                "@type": "CreateAction",
                "agent": {"@id": getpass.getuser()},
                "endTime": end_time,
                "environment": [{"@id": pwd_id}],
                "instrument": {"@id": f"protein-detective@{__version__}"},
                "name": command,
                "object": [
                    {"@id": "refine/refine_run_001/fixed_structure.pdb"},
                    {"@id": "powerfit/run_001/same_structure/fit_1.pdb"},
                ],
                "result": [
                    {"@id": "refine/refine_run_001/io.csv"},
                    {"@id": "refine/refine_run_001/run_001/same_structure/fit_1.pdb/"},
                ],
                "startTime": start_time.isoformat(),
            },
            {"@id": pwd_id, "@type": "PropertyValue", "name": "PWD", "value": str(Path.cwd())},
        ],
    }
    assert metadata["@context"] == expected["@context"]
    assert {item["@id"]: item for item in metadata["@graph"]} == {item["@id"]: item for item in expected["@graph"]}
