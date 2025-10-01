import argparse
import csv
from pathlib import Path


def create_run_script_content(row: dict, map_root: str, interaction_partner_seeds: set[str]) -> str:
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
    res_range_fraction = 0.1 # +- 10%
    min_res = int(float(row["Number of residues modelled"]) * (1 - res_range_fraction))
    max_res = int(float(row["Number of residues modelled"]) * (1 + res_range_fraction))
    interaction_partner_exclude = uniprot
    interaction_partner_seed  = ' \\\n'.join(map(lambda s: f'    --interaction-partner-seed "{s}"', interaction_partner_seeds))

    resolution = float(row["Resolution"])

    powerfit_args = "--gpu 3"

    search = f"""\
protein-detective search \\
    --taxon-id {tax_id} \\
    --subcellular-location-uniprot "{subcellular_uniprot}" \\
    --subcellular-location-go GO:{go_location} \\
    --interaction-partner-exclude "{interaction_partner_exclude}" \\
{interaction_partner_seed} \\
    --limit {search_limit} \\
    .
"""
    if not subcellular_uniprot and not go_location:
        search = f"""\
protein-detective search \\
    --taxon-id {tax_id} \\
    --interaction-partner-exclude "{interaction_partner_exclude}" \\
{interaction_partner_seed} \\    
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
ls -1 downloads/pdbe/{pdb_id.lower()}.cif

# use {min_res} to {max_res} as residue range

if [ ! -d "filtered" ]; then
protein-detective filter \\
    --confidence-threshold 70 \\
    --min-residues {min_res} \\
    --max-residues {max_res} \\
    .
fi

# Is the fitted model {pdb_id}:{chain} still part of the search results?
ls -l filtered/{pdb_id.lower()}_{chain}2A.cif

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

            datasets.append(row)
            previous_row = row

    for dataset in datasets:
        # Create directory structure
        pdb_emdb_dir_name = f"{dataset['PDB_id']}-{dataset['EMDB']}"
        pdb_emdb_dir = benchmark_dir / "work" / pdb_emdb_dir_name
        chain_uniprot_dir = f"{dataset['Chain']}-{dataset['Uniprot_id']}"
        output_dir = pdb_emdb_dir / chain_uniprot_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        interaction_partner_seeds = {row["Uniprot_id"] for row in datasets if row["EMDB"] == dataset["EMDB"] and row["Uniprot_id"] != dataset["Uniprot_id"]}

        # Generate and write run.sh
        script_content = create_run_script_content(dataset, map_root, interaction_partner_seeds)
        run_sh_path = output_dir / "run.sh"
        run_sh_path.write_text(script_content, encoding="utf-8")
        print(f"Generated {run_sh_path}")  # noqa: T201


if __name__ == "__main__":
    main()