import pytest

from protein_detective.pdbe.io import ChainsPositions, parse_uniprot_chain


@pytest.mark.parametrize(
    "query,expected_chains,expected_start,expected_end",
    [
        ("O=1-300", ["O"], 1, 300),  #  uniprot:A8MT69 pdb:7R5S
        ("B/D=1-81", ["B", "D"], 1, 81),  # uniprot:A8MT69 pdb:4E44
        (
            "B/D/H/L/M/N/U/V/W/X/Z/b/d/h/i/j/o/p/q/r=8-81",  # uniprot:A8MT69 pdb:4NE1
            # fmt: off
            ["B", "D", "H", "L", "M", "N", "U", "V", "W", "X", "Z", "b", "d", "h", "i", "j", "o", "p", "q", "r"],
            # fmt: on
            8,
            81,
        ),
    ],
)
def test_parse_uniprot_chain(query, expected_chains, expected_start, expected_end):
    result = parse_uniprot_chain(query)

    expected = ChainsPositions(
        chains=expected_chains,
        start=expected_start,
        end=expected_end,
    )
    assert result == expected
