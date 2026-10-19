import logging
from pathlib import Path
from textwrap import dedent

import pytest
from haddock.gear.prepare_run import setup_run
from protein_quest.structure.chains import chains_in_structure
from protein_quest.structure.formats import read_structure, write_structure

from protein_detective.refine.haddock import (
    RefineOptions,
    generate_haddock3_config_body,
    generate_unrefined_config_body,
    prepare_fitted_and_fixed,
    prepare_fixed_structure,
    set_haddock3_log_level,
)


def test_baseline_complex_preserves_coordinates_and_chains(
    tmp_path: Path, fitted_structure: Path, fixed_structure: Path
):
    result = read_structure(prepare_fitted_and_fixed(fitted_structure, fixed_structure, tmp_path))
    assert [chain.name for chain in result[0]] == ["A", "B"]
    for chain, source in zip(
        result[0], (read_structure(fitted_structure)[0], read_structure(fixed_structure)[0]), strict=True
    ):
        actual = [(atom.name, (atom.pos.x, atom.pos.y, atom.pos.z)) for residue in chain for atom in residue]
        expected = [
            (atom.name, (atom.pos.x, atom.pos.y, atom.pos.z))
            for source_chain in source
            for residue in source_chain
            for atom in residue
        ]
        assert actual == expected


@pytest.mark.parametrize("partner,chain_name", [("fitted", "Z"), ("fixed", "A")])
def test_baseline_rejects_wrong_chains(
    tmp_path: Path, fitted_structure: Path, fixed_structure: Path, partner: str, chain_name: str
):
    inputs = {"fitted": fitted_structure, "fixed": fixed_structure}
    structure = read_structure(inputs[partner])
    structure[0][0].name = chain_name
    wrong = tmp_path / "wrong.pdb"
    write_structure(structure, wrong)
    inputs[partner] = wrong
    with pytest.raises(ValueError, match="must contain only chain"):
        prepare_fitted_and_fixed(inputs["fitted"], inputs["fixed"], tmp_path)
    assert not (tmp_path / "fitted-and-fixed.pdb").exists()


def test_baseline_configuration(tmp_path: Path):
    run = tmp_path / "baseline"
    complex_file = run / "fitted-and-fixed.pdb"
    config = generate_unrefined_config_body(run, complex_file, 3)
    assert config == dedent(f"""\
        run_dir = "{run}"
        mode = "local"
        ncores = 3
        clean = true
        postprocess = true

        molecules = ["{complex_file}"]

        [topoaa]

        [emscoring]

        [caprieval]
        """)


@pytest.fixture
def workflow_config(tmp_path: Path, fitted_structure: Path, fixed_structure: Path, workflow_name: str) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    fitted = inputs / "fitted.pdb"
    write_structure(read_structure(fitted_structure), fitted)
    fixed = prepare_fixed_structure(fixed_structure, inputs)
    run_dir = tmp_path / workflow_name
    run_dir.mkdir()
    config = run_dir / "workflow.cfg"
    if workflow_name == "baseline":
        complex_file = prepare_fitted_and_fixed(fitted, fixed, run_dir)
        body = generate_unrefined_config_body(run_dir, complex_file, 1)
    else:
        body = generate_haddock3_config_body(run_dir, fitted, fixed, RefineOptions())
    config.write_text(body)
    return config


@pytest.mark.parametrize("workflow_name", ["baseline", "refinement"])
def test_workflow_setup_with_config_inside_run_directory(workflow_config: Path, workflow_name: str):
    modules, params = setup_run(workflow_config, restart_from=0)
    assert Path(params["run_dir"]) == workflow_config.parent
    assert workflow_config.is_file()
    assert (workflow_config.parent / "data/configurations").is_dir()
    assert "topoaa.1" in modules


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

            [caprieval]

            [seletopclusts]
            top_clusters = 3
            top_models = 4

            [mdref]
            sampling_factor = 7
            solvent = "dmso"

            [clustfcc]
            min_population = 1
            clust_cutoff = 0.95

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

            [caprieval]

            [seletopclusts]
            top_clusters = 10
            top_models = 2

            [mdref]
            sampling_factor = 1
            solvent = "none"

            [clustfcc]
            min_population = 1
            clust_cutoff = 0.6

            [caprieval]
        """)

        config = generate_haddock3_config_body(run_dir, fitted_model, fixed_structure, options)

        assert config == expected


@pytest.fixture
def haddock_logger():
    logger = logging.getLogger("haddock")
    level, propagate = logger.level, logger.propagate
    handler_levels = [(handler, handler.level) for handler in logger.handlers]
    yield logger
    logger.setLevel(level)
    logger.propagate = propagate
    for handler, handler_level in handler_levels:
        handler.setLevel(handler_level)


def test_set_haddock3_log_level_hides_info(haddock_logger: logging.Logger):
    set_haddock3_log_level(logging.WARNING)

    assert haddock_logger.level == logging.WARNING
    assert {handler.level for handler in haddock_logger.handlers} == {logging.WARNING}
    assert not haddock_logger.propagate
