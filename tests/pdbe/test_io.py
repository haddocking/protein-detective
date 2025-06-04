import pytest

from protein_detective.pdbe.io import first_chain_from_uniprot_chains


@pytest.mark.parametrize(
    "query,expected",
    [
        ("O=1-300", "O"),  #  uniprot:A8MT69 pdb:7R5S
        ("B/D=1-81", "B"),  # uniprot:A8MT69 pdb:4E44
        (
            "B/D/H/L/M/N/U/V/W/X/Z/b/d/h/i/j/o/p/q/r=8-81",  # uniprot:A8MT69 pdb:4NE1
            "B",
        ),
        ("A/B=2-459,A/B=520-610", "A"),  # uniprot/O00255 pdb/3U84
        ("DD/Dd=1-1085", "DD"),  # uniprot/O00268 pdb/7ENA
        ("A=398-459,A=74-386,A=520-584,A=1-53", "A"),  # uniprot/O00255 pdb/7O9T
    ],
)
def test_first_chain_from_uniprot_chains(query, expected):
    result = first_chain_from_uniprot_chains(query)

    assert result == expected
