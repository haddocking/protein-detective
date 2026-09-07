from pathlib import Path
from textwrap import dedent

import pytest
from protein_quest.structure.chains import chains_in_structure
from protein_quest.structure.formats import read_structure, write_structure

from protein_detective.refine import (
    RefineOptions,
    generate_haddock3_config_body,
    prepare_fixed_structure,
    refine_with_haddock3,
)


class TestPrepareFixedStructure:
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
        options=RefineOptions(
            rigidbody_sampling=10,
        ),
        scheduler_address="sequential",
    )
