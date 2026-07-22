from pathlib import Path

import pytest

from tests.helpers import cli, fake_run_retrieve


def test_commands_help(capsys: pytest.CaptureFixture[str]):
    argv = ["powerfit", "commands", "--help"]
    cli(argv)

    expected = "Generate PowerFit commands for structure files in the session directory."
    captured = capsys.readouterr()
    assert expected in captured.out


def test_commands_defaults(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    # Fake retrieve + filter
    session_dir = fake_run_retrieve(tmp_path)
    combined_filter_output = session_dir / "combined_output"
    combined_filter_output.mkdir()
    (session_dir / "combined_output" / "2y29_updated.cif.gz").symlink_to(
        session_dir / "downloads" / "pdbe" / "2y29_updated.cif.gz"
    )
    (session_dir / "combined_output" / "AF-A0A0C5B5G6-F1-model_v6.cif.gz").symlink_to(
        session_dir / "downloads" / "alphafold" / "AF-A0A0C5B5G6-F1-model_v6.cif.gz"
    )
    # Fake target
    target = tmp_path / "target.mrc"
    target.write_text("fake density map")

    argv = [
        "powerfit",
        "commands",
        str(target),
        "3.0",
        str(session_dir),
    ]
    cli(argv)

    stdout = capsys.readouterr().out
    assert "# Run the commands below in your own way" in stdout
    assert (
        f"powerfit {session_dir}/powerfit/run_001/target.mrc 3.0 {session_dir}/combined_output/AF-A0A0C5B5G6-F1-model_v6.cif.gz --resampling-rate 2.0 --num 0 --nproc 1 --directory {session_dir}/powerfit/run_001/AF-A0A0C5B5G6-F1-model_v6.cif --delimiter , --angle 10.0"
        in stdout
    )
    assert (
        f"powerfit {session_dir}/powerfit/run_001/target.mrc 3.0 {session_dir}/combined_output/2y29_updated.cif.gz --resampling-rate 2.0 --num 0 --nproc 1 --directory {session_dir}/powerfit/run_001/2y29_updated.cif --delimiter , --angle 10.0"
        in stdout
    )
