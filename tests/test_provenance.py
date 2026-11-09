import pytest

from protein_detective.provenance import command_arguments


@pytest.mark.parametrize(
    "invocation, expected",
    [
        ("protein-detective refine run session known.pdb --count 2", (["session", "known.pdb"], ["--count", "2"])),
        (
            "'/old path/protein-detective' refine run --flag 'session name' --count=2 'known partner.pdb'",
            (["session name", "known partner.pdb"], ["--flag", "--count", "2"]),
        ),
        ("protein-detective refine run --flag -- -session -known", (["-session", "-known"], ["--flag"])),
        ("protein-detective refine run session known --count", None),
        ("protein-detective refine run session known --count -2", (["session", "known"], ["--count", "-2"])),
        ("protein-detective refine run same --count same same", (["same", "same"], ["--count", "same"])),
        ("protein-detective refine run session known --cou 2", None),
        ("protein-detective refine run --unknown value session known", None),
        ("protein-detective refine run 'unterminated", None),
        ("protein-detective refine run-extra session known", None),
        ("another-program refine run session known", None),
    ],
)
def test_recorded_command_arguments(invocation: str, expected: tuple[list[str], list[str]] | None):
    assert (
        command_arguments(invocation, ("protein-detective", "refine", "run"), {"--count": True, "--flag": False})
        == expected
    )
