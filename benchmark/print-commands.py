"""
This script generates run.sh files for benchmarking based on a CSV file.

It reads benchmark data from "Benchmarklist.csv", and for each relevant
row, it creates a directory structure and a corresponding run.sh script
to execute a protein-detective pipeline.
"""

import csv
from pathlib import Path


def create_run_script_content(row: dict) -> str:
    """Generate the content of a run.sh script from a CSV row."""
    emdb_id = row["EMDB"]
    uniprot = row["Uniprot_id"]
    tax_id = row["Ncbi tax id"]
    subcellular_uniprot = row["First cellular location - Uniprot"]
    go_location = row["First (larger) cellular location - GO"]
    pdb_id = row["PDB_id"].strip()
    chain = row["Chain"]
    # Use a range around the modelled residues for filtering
    # TODO use better logic to determine min/max residues based on the volume of the unknown density
    min_res = int(row["Number of residues modelled"]) - 40
    max_res = int(row["Number of residues modelled"]) + 40

    resolution = float(row["Resolution"])

    map_file = f"../emd_{emdb_id}.map"
    map_gz_file = f"../emd_{emdb_id}.map.gz"
    masked_map = f"emd_{emdb_id}-{uniprot}_{pdb_id.lower()}_{chain}2A.mrc"
    # TODO document how to figure out what is good argument for --gpu, aka if gpu is not fully utilized then ++
    powerfit_args = "--gpu 3"

    return f"""\
#!/bin/bash

set -euxo pipefail

if [ ! -f "{map_file}" ]; then
    wget https://ftp.ebi.ac.uk/pub/databases/emdb/structures/EMD-{emdb_id}/map/emd_{emdb_id}.map.gz -O {map_gz_file}
    gunzip {map_gz_file}
fi

protein-detective search \\
    --taxon-id {tax_id} \\
    --subcellular-location-uniprot "{subcellular_uniprot}" \\
    --subcellular-location-go GO:{go_location} \\
    --limit 50000 \\
    .

protein-detective retrieve .

# Is fitted model {pdb_id}:{chain} part of the search results?
ls -1 downloads/{pdb_id.lower()}.cif

# use {min_res} to {max_res} as residue range

protein-detective density-filter \\
    --confidence-threshold 70 \\
    --min-residues {min_res} \\
    --max-residues {max_res} \\
    .

protein-detective prune-pdbs \\
    --min-residues {min_res} \\
    --max-residues {max_res} \\
    .

# prep density for just unknown volume
cat > prep.cxc << EOF
open {map_file};
open single_chain/{uniprot}_{pdb_id.lower()}_{chain}2A.pdb;
molmap #2 {resolution} balls true;
volume mask #1 surfaces #3 pad 4;
save {masked_map} #4;
exit
EOF
chimerax --nogui --script prep.cxc

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
            pdb_emdb_dir_name = f"PDB{row['PDB_id']}-EMDB{row['EMDB']}"
            pdb_emdb_dir = benchmark_dir / pdb_emdb_dir_name
            chain_uniprot_dir = f"{row['Chain']}-{row['Uniprot_id']}"
            output_dir = pdb_emdb_dir / chain_uniprot_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate and write run.sh
            script_content = create_run_script_content(row)
            run_sh_path = output_dir / "run.sh"
            run_sh_path.write_text(script_content, encoding="utf-8")
            print(f"Generated {run_sh_path}")  # noqa: T201
            previous_row = row


if __name__ == "__main__":
    main()
