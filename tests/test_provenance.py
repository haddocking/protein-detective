import pytest

from protein_detective.provenance import command_arguments


@pytest.mark.parametrize(
    "invocation, expected",
    [
        ("protein-detective refine run session fixed.pdb --count 2", (["session", "fixed.pdb"], ["--count", "2"])),
        (
            "'/old path/protein-detective' refine run --flag 'session name' --count=2 'fixed partner.pdb'",
            (["session name", "fixed partner.pdb"], ["--flag", "--count", "2"]),
        ),
        ("protein-detective refine run --flag -- -session -fixed", (["-session", "-fixed"], ["--flag"])),
        ("protein-detective refine run session fixed --count", None),
        ("protein-detective refine run session fixed --count -2", (["session", "fixed"], ["--count", "-2"])),
        ("protein-detective refine run same --count same same", (["same", "same"], ["--count", "same"])),
        ("protein-detective refine run session fixed --cou 2", None),
        ("protein-detective refine run --unknown value session fixed", None),
        ("protein-detective refine run 'unterminated", None),
        ("protein-detective refine run-extra session fixed", None),
        ("another-program refine run session fixed", None),
    ],
)
def test_recorded_command_arguments(invocation: str, expected: tuple[list[str], list[str]] | None):
    assert (
        command_arguments(invocation, ("protein-detective", "refine", "run"), {"--count": True, "--flag": False})
        == expected
    )
