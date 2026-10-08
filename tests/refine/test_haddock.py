from pathlib import Path
from textwrap import dedent

import pytest
from protein_quest.structure.chains import chains_in_structure
from protein_quest.structure.formats import read_structure

from protein_detective.refine.haddock import RefineOptions, generate_haddock3_config_body, prepare_fixed_structure


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

        result_chains = [c.name for c in chains_in_structure(read_structure(fixed_structure))]

        assert fixed_structure == refine_dir / "fixed_structure.pdb"
        assert fixed_structure.exists()
        assert result_chains == ["B"]

    def test_renames_all_chains_to_custom_out_chain(self, tmp_path: Path, cif_1gru: Path):
        refine_dir = tmp_path / "refine"
        refine_dir.mkdir()

        fixed_structure = prepare_fixed_structure(cif_1gru, refine_dir, out_chain="Z")

        result_chains = {c.name for c in chains_in_structure(read_structure(fixed_structure))}

        assert fixed_structure == refine_dir / "fixed_structure.pdb"
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
            fcc_clust_cutoff=0.95,
        )

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
            clust_cutoff = 0.95

            [caprieval]

            [seletopclusts]
            top_clusters = 3
            top_models = 4

            [mdref]
            sampling_factor = 7
            solvent = "dmso"

            [caprieval]
        """)

        config = generate_haddock3_config_body(run_dir, fitted_model, fixed_structure, options)

        assert config == expected

    def test_default_options(self, tmp_path: Path):
        run_dir = tmp_path / "refine" / "run_001"
        fitted_model = tmp_path / "fit_1.pdb"
        fixed_structure = tmp_path / "fixed_structure.pdb"
        options = RefineOptions()

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
            clust_cutoff = 0.6

            [caprieval]

            [seletopclusts]
            top_clusters = 10
            top_models = 2

            [mdref]
            sampling_factor = 1
            solvent = "none"

            [caprieval]
        """)

        config = generate_haddock3_config_body(run_dir, fitted_model, fixed_structure, options)

        assert config == expected
