import csv
from dataclasses import dataclass
from pathlib import Path

from cattrs import Converter
from cattrs.gen import make_dict_structure_fn, override

benchmark_dir = Path(__file__).parent
root_work_dir = benchmark_dir / "work"

# The xlsx file was converted to csv and modified by removing angstrom from header
csv_path = benchmark_dir / "Benchmarklist.csv"
map_root = "/trinity/login/aengle/pipeline_project/simulated_benchmark/pdbs"

@dataclass
class Dataset:
    PDB_id: str
    EMDB: str
    Name: str
    Resolution: str
    Water_Membrane_soluble_complex: str
    Chain: str
    Uniprot_id: str
    First_larger_cellular_location_GO: str
    First_cellular_location_Uniprot: str
    Number_of_residues_in_construct: int
    Number_of_residues_in_uniprot: int
    Number_of_residues_modelled: int
    Source_Organism: str
    Ncbi_tax_id: str
    Unmodeled_based_on_provided_sequence: str
    output_dir: Path

c = Converter()
c.register_structure_hook(
    Dataset,
    make_dict_structure_fn(
        Dataset,
        c,
        Water_Membrane_soluble_complex=override(rename="Water/Membrane soluble complex"),
        First_larger_cellular_location_GO=override(rename="First (larger) cellular location - GO"),
        First_cellular_location_Uniprot=override(rename="First cellular location - Uniprot"),
        Number_of_residues_in_construct=override(rename="Number of residues in construct"),
        Number_of_residues_in_uniprot=override(rename="Number of residues in uniprot"),
        Number_of_residues_modelled=override(rename="Number of residues modelled"),
        Source_Organism=override(rename="Source Organism"),
        Ncbi_tax_id=override(rename="Ncbi tax id"),
        Unmodeled_based_on_provided_sequence=override(rename="Unmodeled based on provided sequence"),
    )
)

def parse_benchmark_csv(csv_path) -> list[Dataset]:
    with csv_path.open(newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        previous_row = {}
        datasets = []
        for row in reader:
            # Persist PDB and EMDB IDs for rows that are part of the same complex
            for key, value in row.items():
                if not value and key in previous_row:
                    row[key] = previous_row[key]

            # Skip rows without essential information
            if not all(
                [
                    row["PDB_id"],
                    row["EMDB"],
                    row["Chain"],
                    row["Uniprot_id"],
                    row["Number of residues modelled"],
                ]
            ):
                previous_row = row
                continue

            pdb_emdb_dir_name = f"{row['PDB_id']}-{row['EMDB']}"
            pdb_emdb_dir = root_work_dir / pdb_emdb_dir_name
            chain_uniprot_dir = f"{row['Chain']}-{row['Uniprot_id']}"
            output_dir = pdb_emdb_dir / chain_uniprot_dir
            row["output_dir"] = output_dir
            datasets.append(c.structure(row, Dataset))
            previous_row = row
    return datasets

datasets = parse_benchmark_csv(csv_path)

