import pytest

from tests.helpers import cli


def test_commands_help(capsys: pytest.CaptureFixture[str]):
    argv = ["powerfit", "commands", "--help"]
    cli(argv)

    expected = "Generate PowerFit commands for structure files in the session directory."
    captured = capsys.readouterr()
    assert expected in captured.out
