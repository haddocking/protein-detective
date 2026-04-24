from pathlib import Path
from typing import TYPE_CHECKING

from protein_detective.db import connect, save_uniprot_details

if TYPE_CHECKING:
    from protein_quest.uniprot import UniprotDetails


def test_save_uniprot_details(tmp_path: Path):
    details: list[UniprotDetails] = [
        {
            "uniprot_accession": "P12345",
            "uniprot_id": "PROT_HUMAN",
            "sequence_length": 350,
            "reviewed": True,
            "protein_name": "Example Protein",
            "taxon_id": 9606,
            "taxon_name": "Homo sapiens",
        }
    ]
    with connect(tmp_path) as con:
        save_uniprot_details(details, con)

        rows = con.execute("SELECT * FROM proteins").fetchall()
        expected = [("P12345", "PROT_HUMAN", 350, True, "Example Protein", 9606, "Homo sapiens")]
        assert rows == expected
