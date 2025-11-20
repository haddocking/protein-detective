from pdconfig import Dataset, datasets, map_root


def create_run_script_content(row: Dataset, map_root: str, interaction_partner_seeds: set[str]) -> str:
    """Generate the content of a run.sh script from a CSV row."""
    uniprot = row.Uniprot_id
    tax_id = row.Ncbi_tax_id
    subcellular_uniprot = row.First_cellular_location_Uniprot.replace("\\", "")
    go_location = row.First_larger_cellular_location_GO.replace("\\", "")
    search_limit = 100_000
    pdb_id = row.PDB_id
    chain = row.Chain
    # Use a range around the modelled residues for filtering
    # TODO use better logic to determine min/max residues based on the volume of the unknown density
    sorf_res_range_fraction = 0.1  # +- 10%
    soft_min_res = int(float(row.Number_of_residues_modelled) * (1 - sorf_res_range_fraction))
    soft_max_res = int(float(row.Number_of_residues_modelled) * (1 + sorf_res_range_fraction))
    hard_min_res = int(float(row.Number_of_residues_modelled) * (0.8))  # at least 80%
    hard_max_res = int(float(row.Number_of_residues_modelled) * (1.5))  # at most 150%
    interaction_partner_exclude = uniprot
    interaction_partner_seed = " \\\n".join(f'    --interaction-partner-seed "{s}"' for s in interaction_partner_seeds)
    resolution = float(row.Resolution)
    number_of_workers_per_gpu = 3
    powerfit_args = f"--gpu {number_of_workers_per_gpu}"

    search = f"""\
protein-detective search \\
    --taxon-id {tax_id} \\
    --subcellular-location-uniprot "{subcellular_uniprot}" \\
    --subcellular-location-go GO:{go_location} \\
    --interaction-partner-exclude "{interaction_partner_exclude}" \\
{interaction_partner_seed}\
    --min-residues {soft_min_res} \\
    --max-residues {hard_max_res} \\
    --min-sequence-length {hard_min_res} \\
    --limit {search_limit} \\
    .
"""
    if not subcellular_uniprot and not go_location:
        search = f"""\
protein-detective search \\
    --taxon-id {tax_id} \\
    --interaction-partner-exclude "{interaction_partner_exclude}" \\
{interaction_partner_seed} \\
    --min-residues {soft_min_res} \\
    --max-residues {hard_max_res} \\
    --min-sequence-length {hard_min_res} \\
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
ls -1 downloads/pdbe/{pdb_id.lower()}.cif.gz

if [ ! -d "filtered" ]; then
protein-detective filter \\
    --confidence-threshold 70 \\
    --min-residues {soft_min_res} \\
    --max-residues {soft_max_res} \\
    .
fi

# Is the fitted model {pdb_id}:{chain} still part of the search results?
ls -1 filtered/{pdb_id.lower()}_{chain}2A.cif.gz

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
    for dataset in datasets:
        output_dir = dataset.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Group proteins in the same emdb entry as interaction partners
        interaction_partner_seeds = {
            row.Uniprot_id for row in datasets if row.EMDB == dataset.EMDB and row.Uniprot_id != dataset.Uniprot_id
        }

        # Generate and write run.sh
        # TODO split run scrip in 3 stages: search+retrieve, filter, and powerfit
        # as search+retrieve talks to remote servers it is better to run sequentially
        # and filter can run in parallel on CPU
        # and powerfit can be run in parallel on GPU
        script_content = create_run_script_content(dataset, map_root, interaction_partner_seeds)
        run_sh_path = output_dir / "run.sh"
        run_sh_path.write_text(script_content, encoding="utf-8")
        print(f"Generated {run_sh_path}")  # noqa: T201


if __name__ == "__main__":
    main()
