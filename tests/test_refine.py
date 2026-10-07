from pathlib import Path
from textwrap import dedent

import pytest
from cyclopts import ValidationError
from protein_quest.structure.chains import chains_in_structure
from protein_quest.structure.formats import read_structure, write_structure

from protein_detective.cli import app
from protein_detective.refine import (
    RefineOptions,
    generate_haddock3_config_body,
    prepare_fixed_structure,
    refine_with_haddock3,
)
from tests.helpers import assert_crate, assert_lines


@pytest.mark.parametrize("ncores", [-2, -1, 0])
def test_refine_cli_rejects_nonpositive_ncores(tmp_path: Path, ncores: int):
    fixed_structure = tmp_path / "fixed.pdb"
    fixed_structure.touch()
    with pytest.raises(ValidationError, match="Must be > 0"):
        app.parse_args(
            ["refine", str(tmp_path), str(fixed_structure), "--ncores", str(ncores)],
            exit_on_error=False,
            print_error=False,
        )


@pytest.mark.parametrize("chains", [["A", "C"], ["A", "C", "A"]])
def test_refine_cli_accepts_fixed_chain_removal(tmp_path: Path, chains: list[str]):
    fixed_structure = tmp_path / "fixed.pdb"
    fixed_structure.touch()

    _, bound, _ = app.parse_args(
        ["refine", str(tmp_path), str(fixed_structure)]
        + [token for chain in chains for token in ("--remove-fixed-chains", chain)],
        exit_on_error=False,
        print_error=False,
    )

    assert bound.arguments["remove_fixed_chains"] == {"A", "C"}


class TestPrepareFixedStructure:
    @pytest.mark.parametrize("remove_fixed_chains", [{"B"}, {"A", "C"}, set()])
    def test_removes_original_chains_before_renaming(
        self, tmp_path: Path, cif_1gru: Path, remove_fixed_chains: set[str]
    ):
        original = read_structure(cif_1gru)
        expected_atom_count = sum(
            len(residue)
            for model in original
            for chain in model
            if chain.name not in remove_fixed_chains
            for residue in chain
        )

        result = read_structure(prepare_fixed_structure(cif_1gru, tmp_path, remove_fixed_chains=remove_fixed_chains))

        assert len(result) == len(original)
        assert {chain.name for chain in chains_in_structure(result)} == {"B"}
        assert result[0].count_atom_sites() == expected_atom_count

    def test_rejects_missing_chain(self, tmp_path: Path, cif_1gru: Path):
        with pytest.raises(ValueError, match=r"Chains not found.*X"):
            prepare_fixed_structure(cif_1gru, tmp_path, remove_fixed_chains={"X"})

        assert not (tmp_path / "fixed_structure.pdb").exists()

    def test_rejects_removing_all_chains(self, tmp_path: Path, cif_1gru: Path):
        all_chains = {chain.name for chain in chains_in_structure(read_structure(cif_1gru))}

        with pytest.raises(ValueError, match="Cannot remove all chains"):
            prepare_fixed_structure(cif_1gru, tmp_path, remove_fixed_chains=all_chains)

        assert not (tmp_path / "fixed_structure.pdb").exists()

    def test_renames_all_chains_to_b(self, tmp_path: Path, cif_1gru: Path):
        refine_dir = tmp_path / "refine"
        refine_dir.mkdir()

        fixed_structure = prepare_fixed_structure(cif_1gru, refine_dir)

        assert fixed_structure == refine_dir / "fixed_structure.pdb"
        assert fixed_structure.exists()
        result_chains = [c.name for c in chains_in_structure(read_structure(fixed_structure))]
        assert result_chains == ["B"]

    def test_renames_all_chains_to_custom_out_chain(self, tmp_path: Path, cif_1gru: Path):
        refine_dir = tmp_path / "refine"
        refine_dir.mkdir()

        fixed_structure = prepare_fixed_structure(cif_1gru, refine_dir, out_chain="Z")

        assert fixed_structure == refine_dir / "fixed_structure.pdb"
        result_chains = {c.name for c in chains_in_structure(read_structure(fixed_structure))}
        assert result_chains == {"Z"}

    def test_input_has_multiple_chains(self, cif_1gru: Path):
        input_chains = {c.name for c in chains_in_structure(read_structure(cif_1gru))}
        assert len(input_chains) == 21


class TestGenerateHaddock3ConfigBody:
    def test_custom_options(self, tmp_path: Path):
        run_dir = tmp_path / "refine" / "run_001"
        fitted_model = tmp_path / "powerfit" / "run_001" / "model.cif.gz" / "fit_1.pdb"
        fixed_structure = tmp_path / "fixed_structure.pdb"
        options = RefineOptions(
            rigidbody_sampling=42,
            top_clusters=3,
            top_models=4,
            water_refinement_sampling_factor=7,
            water_refinement_solvent="dmso",
            ncores=8,
        )

        config = generate_haddock3_config_body(run_dir, fitted_model, fixed_structure, options)

        expected = dedent(f"""\
            run_dir = "{run_dir}"
            mode = "local"
            ncores = 8
            clean = true
            postprocess = true

            molecules = [
                "{fitted_model}",
                "{fixed_structure}"
            ]

            [topoaa]

            [rigidbody]
            separate = false
            mol_fix_origin_2 = true
            sampling = 42
            cmrest = true

            [caprieval]

            [clustfcc]
            min_population = 1

            [caprieval]

            [seletopclusts]
            top_clusters = 3
            top_models = 4

            [mdref]
            sampling_factor = 7
            solvent = "dmso"

            [caprieval]
        """)
        assert config == expected

    def test_default_options(self, tmp_path: Path):
        run_dir = tmp_path / "refine" / "run_001"
        fitted_model = tmp_path / "fit_1.pdb"
        fixed_structure = tmp_path / "fixed_structure.pdb"
        options = RefineOptions()

        config = generate_haddock3_config_body(run_dir, fitted_model, fixed_structure, options)

        expected = dedent(f"""\
            run_dir = "{run_dir}"
            mode = "local"
            ncores = 1
            clean = true
            postprocess = true

            molecules = [
                "{fitted_model}",
                "{fixed_structure}"
            ]

            [topoaa]

            [rigidbody]
            separate = false
            mol_fix_origin_2 = true
            sampling = 1000
            cmrest = true

            [caprieval]

            [clustfcc]
            min_population = 1

            [caprieval]

            [seletopclusts]
            top_clusters = 10
            top_models = 2

            [mdref]
            sampling_factor = 1
            solvent = "none"

            [caprieval]
        """)
        assert config == expected


@pytest.mark.manual
def test_refine_with_haddock3(tmp_path: Path, cif_9a2g: Path, cif_1gru_groes: Path):
    fixed_structure = cif_1gru_groes
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True)
    powerfit_root_dir = session_dir / "powerfit"
    powerfit_run_dir = powerfit_root_dir / "run_001" / "fakestructure.cif"
    powerfit_run_dir.mkdir(parents=True)
    fitted_model = powerfit_run_dir / "fit_1.pdb"
    # Need pdb format so convert
    write_structure(read_structure(cif_9a2g), fitted_model)
    # fake fitted_models.csv
    fitted_models_csv = powerfit_root_dir / "fitted_models.csv"
    fitted_models_csv.write_text("fitted_model_file\npowerfit/run_001/fakestructure.cif/fit_1.pdb\n")

    refine_with_haddock3(
        session_dir,
        fixed_structure,
        refine_options=RefineOptions(
            rigidbody_sampling=10,
            ncores=6,
        ),
        scheduler_address="sequential",
    )

    assert (session_dir / "refine/run_001/fakestructure.cif/fit_1.pdb/6_mdref/mdref_1.pdb.gz").exists()
    expected_io_csv_lines = {
        "fitted_model,refine_run_dir",
        "powerfit/run_001/fakestructure.cif/fit_1.pdb,refine/run_001/fakestructure.cif/fit_1.pdb",
    }
    assert_lines(session_dir / "refine/io.csv", expected_io_csv_lines)
    crate_input_ids = {
        "refine/fixed_structure.pdb",
        "powerfit/run_001/fakestructure.cif/fit_1.pdb",
    }
    crate_output_ids = {
        "refine/io.csv",
        "refine/run_001/fakestructure.cif/fit_1.pdb/",
    }
    _, expected_action = assert_crate(
        Path("manual-refine-test-output/session"),
        input_ids=crate_input_ids,
        output_ids=crate_output_ids,
    )
    _, actual_action = assert_crate(
        session_dir,
        input_ids=crate_input_ids,
        output_ids=crate_output_ids,
    )
    assert {i["@id"] for i in actual_action["object"]} == {i["@id"] for i in expected_action["object"]}
    assert {o["@id"] for o in actual_action["result"]} == {o["@id"] for o in expected_action["result"]}
