import argparse
import csv
from pathlib import Path


def create_run_script_content(row: dict, map_root: str) -> str:
    """Generate the content of a run.sh script from a CSV row."""
    emdb_id = row["EMDB"]
    uniprot = row["Uniprot_id"]
    tax_id = row["Ncbi tax id"]
    subcellular_uniprot = row["First cellular location - Uniprot"].replace("\\", "")
    go_location = row["First (larger) cellular location - GO"].replace("\\", "")
    search_limit = 100_000
    pdb_id = row["PDB_id"]
    chain = row["Chain"]
    # Use a range around the modelled residues for filtering
    # TODO use better logic to determine min/max residues based on the volume of the unknown density
    min_res = int(row["Number of residues modelled"]) - 40
    max_res = int(row["Number of residues modelled"]) + 40

    resolution = float(row["Resolution"])

    powerfit_args = "--gpu 3"

    search = f"""\
protein-detective search \\
    --taxon-id {tax_id} \\
    --subcellular-location-uniprot "{subcellular_uniprot}" \\
    --subcellular-location-go GO:{go_location} \\
    --limit {search_limit} \\
    .
"""
    if not subcellular_uniprot and not go_location:
        search = f"""\
protein-detective search \\
    --taxon-id {tax_id} \\
    --limit {search_limit} \\
    .
"""

    resampled_resolution = "6"
    masked_map = f"{map_root}/{pdb_id}/situs/{pdb_id}_{resampled_resolution}_{chain}.mrc"

    return f"""\
#!/bin/bash

set -euxo pipefail

echo $PWD

if [ ! -d "downloads" ]; then
{search}
protein-detective retrieve .
fi

# Is fitted model {pdb_id}:{chain} part of the search results?
ls -1 downloads/{pdb_id.lower()}.cif.gz

# use {min_res} to {max_res} as residue range

if [ ! -d "density_filtered" ]; then
protein-detective density-filter \\
    --confidence-threshold 70 \\
    --min-residues {min_res} \\
    --max-residues {max_res} \\
    .
fi

if [ ! -d "single_chain" ]; then
protein-detective prune-pdbs \\
    --min-residues {min_res} \\
    --max-residues {max_res} \\
    .
fi

# Is the fitted model {pdb_id}:{chain} still part of the search results?
ls -l single_chain/{uniprot}_{pdb_id.lower()}_{chain}2A.pdb

# powerfit
protein-detective powerfit run {masked_map} {resolution} . {powerfit_args}

protein-detective powerfit report .

# Write all fitted pdbs
protein-detective powerfit fit-models . --top 100

# View known model + unknown density + fitted models in mol* or chimeraX
"""


def main():
    """
    Main function to read the CSV and generate benchmark scripts.
    """
    benchmark_dir = Path(__file__).parent
    csv_path = benchmark_dir / "Benchmarklist.csv"

    parser = argparse.ArgumentParser(description="Generate benchmark scripts from CSV.")
    parser.add_argument(
        "--map_root",
        help="Root directory for the maps.",
        default="/trinity/login/aengle/pipeline_project/simulated_benchmark/pdbs",
    )
    args = parser.parse_args()
    map_root = args.map_root

    with csv_path.open(newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        previous_row = {}
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

            # Create directory structure
            pdb_emdb_dir_name = f"{row['PDB_id']}-{row['EMDB']}"
            pdb_emdb_dir = benchmark_dir / "work" / pdb_emdb_dir_name
            chain_uniprot_dir = f"{row['Chain']}-{row['Uniprot_id']}"
            output_dir = pdb_emdb_dir / chain_uniprot_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate and write run.sh
            script_content = create_run_script_content(row, map_root)
            run_sh_path = output_dir / "run.sh"
            run_sh_path.write_text(script_content, encoding="utf-8")
            print(f"Generated {run_sh_path}")  # noqa: T201
            previous_row = row


if __name__ == "__main__":
    main()
