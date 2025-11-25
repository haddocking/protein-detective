from textwrap import dedent, indent

from pdconfig import Dataset, benchmark_dir, datasets, map_root


def residue_ranges(number_of_residues_modelled: str | int | float) -> tuple[int, int, int, int]:
    """Calculate soft/hard minimum and maximum residues based on modelled residues count.

    Uses a range fraction of 0.1 (+- 10%) around the modelled residues.

    Args:
        number_of_residues_modelled: Number of modelled residues (as string, int, or float)

    Returns:
        Tuple of (soft_min_res, soft_max_res, hard_min_res, hard_max_res)
    """
    # TODO use better logic to determine min/max residues based on the volume of the unknown density
    soft_res_range_fraction = 0.1  # +- 10%
    base_count = float(number_of_residues_modelled)
    soft_min_res = int(base_count * (1 - soft_res_range_fraction))
    soft_max_res = int(base_count * (1 + soft_res_range_fraction))
    hard_min_res = int(base_count * (0.8))  # at least 80%
    hard_max_res = int(base_count * (1.5))  # at most 150%
    return soft_min_res, soft_max_res, hard_min_res, hard_max_res


def create_remote_script_content(row: Dataset, interaction_partner_seeds: set[str]) -> str:
    """Generate the content of a remote.sh script for search and retrieve stages."""
    uniprot = row.Uniprot_id
    tax_id = row.Ncbi_tax_id
    subcellular_uniprot = row.First_cellular_location_Uniprot.replace("\\", "")
    go_location = row.First_larger_cellular_location_GO.replace("\\", "")
    search_limit = 100_000
    pdb_id = row.PDB_id
    chain = row.Chain
    # Use a range around the modelled residues for filtering
    # TODO use better logic to determine min/max residues based on the volume of the unknown density
    soft_min_res, _, hard_min_res, hard_max_res = residue_ranges(row.Number_of_residues_modelled)

    interaction_partner_exclude = uniprot
    interaction_partner_seed = " \\\n".join(f'--interaction-partner-seed "{s}"' for s in interaction_partner_seeds)

    search = dedent(f"""\
        protein-detective search \\
            --taxon-id {tax_id} \\
            --subcellular-location-uniprot "{subcellular_uniprot}" \\
            --subcellular-location-go GO:{go_location} \\
            --interaction-partner-exclude "{interaction_partner_exclude}" \\
        {indent(interaction_partner_seed, "            ")} --min-residues {soft_min_res} \\
            --max-residues {hard_max_res} \\
            --min-sequence-length {hard_min_res} \\
            --limit {search_limit} \\
            .
        """)
    if not subcellular_uniprot and not go_location:
        search = dedent(f"""\
            protein-detective search \\
                --taxon-id {tax_id} \\
                --interaction-partner-exclude "{interaction_partner_exclude}" \\
            {indent(interaction_partner_seed, "            ")} \\
                --min-residues {soft_min_res} \\
                --max-residues {hard_max_res} \\
                --min-sequence-length {hard_min_res} \\
                --limit {search_limit} \\
                .
            """)

    return dedent(f"""\
        #!/bin/bash

        set -euxo pipefail

        echo $PWD

        if [ ! -d "downloads" ]; then
        {indent(search, "        ")}
        protein-detective retrieve .
        fi

        # Is fitted model {pdb_id}:{chain} part of the search results?
        ls -1 downloads/pdbe/{pdb_id.lower()}.cif.gz
        """)


def create_filter_script_content(row: Dataset) -> str:
    """Generate the content of a filter.sh script for filtering stage."""
    pdb_id = row.PDB_id
    chain = row.Chain
    # Use a range around the modelled residues for filtering
    soft_min_res, soft_max_res, _, _ = residue_ranges(row.Number_of_residues_modelled)

    return dedent(f"""\
        #!/bin/bash

        echo $PWD

        if [ ! -d "filtered" ]; then
        protein-detective filter \\
            --confidence-threshold 70 \\
            --min-residues {soft_min_res} \\
            --max-residues {soft_max_res} \\
            .
        fi

        # Is the fitted model {pdb_id}:{chain} still part of the search results?
        ls -1 filtered/{pdb_id.lower()}_{chain}2A.cif.gz
        """)


def create_powerfit_script_content(row: Dataset, map_root: str) -> str:
    """Generate the content of a powerfit.sh script for powerfit stage."""
    pdb_id = row.PDB_id
    chain = row.Chain
    resolution = float(row.Resolution)
    number_of_workers_per_gpu = 3
    powerfit_args = f"--gpu {number_of_workers_per_gpu}"
    resampled_resolution = "6"
    masked_map = f"{map_root}/{pdb_id}/situs/{pdb_id}_{resampled_resolution}_{chain}.mrc"
    top_fitted_pdbs2generate = 100

    # TODO non-run commands does not need GPU, so run on CPU.
    return dedent(f"""\
        #!/bin/bash

        set -euxo pipefail

        echo $PWD

        # powerfit
        protein-detective powerfit run {powerfit_args} {masked_map} {resolution} .

        protein-detective powerfit report . > powerfit_report.csv

        # Write all fitted pdbs
        protein-detective powerfit fit-models . --top {top_fitted_pdbs2generate}

        # View known model + unknown density + fitted models in mol* or chimeraX
        """)


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

        # Generate and write remote.sh (search+retrieve stage)
        remote_script_content = create_remote_script_content(dataset, interaction_partner_seeds)
        remote_sh_path = output_dir / "remote.sh"
        remote_sh_path.write_text(remote_script_content, encoding="utf-8")
        print(f"Generated {remote_sh_path}")  # noqa: T201

        # Generate and write filter.sh (filter stage)
        filter_script_content = create_filter_script_content(dataset)
        filter_sh_path = output_dir / "filter.sh"
        filter_sh_path.write_text(filter_script_content, encoding="utf-8")
        print(f"Generated {filter_sh_path}")  # noqa: T201

        # Generate and write powerfit.sh (powerfit stage)
        powerfit_script_content = create_powerfit_script_content(dataset, map_root)
        powerfit_sh_path = output_dir / "powerfit.sh"
        powerfit_sh_path.write_text(powerfit_script_content, encoding="utf-8")
        print(f"Generated {powerfit_sh_path}")  # noqa: T201

    (benchmark_dir / "remote_many.sh").write_text(
        dedent("""\
        #!/bin/bash
        set -euxo pipefail

        #SBATCH --nodes=1
        #SBATCH --ntasks-per-node=1
        #SBATCH --cpus-per-task=1
        #SBATCH --partition=medium
        #SBATCH --exclude=node011

        # Make progressbar less chatty
        export TQDM_MININTERVAL=9

        . ../.venv/bin/activate
        find work -name remote.sh -execdir bash {} \\;
        """)
    )

    (benchmark_dir / "filter_many.sh").write_text(
        dedent(f"""\
        #!/bin/bash
        set -euxo pipefail

        #SBATCH --nodes=1
        #SBATCH --ntasks-per-node=1
        #SBATCH --cpus-per-task=16
        #SBATCH --partition=medium
        #SBATCH --exclude=node011
        #SBATCH --array=1-{len(datasets)}

        # Make progressbar less chatty
        export TQDM_MININTERVAL=9

        # Convert SLURM_ARRAY_TASK_ID to directory
        mapfile -t JOB_DIRS < <(find work -name filter.sh -printf "%h\\n" | sort)
        DIR="${{JOB_DIRS[$SLURM_ARRAY_TASK_ID - 1]}}"

        . ../.venv/bin/activate
        srun --chdir $DIR filter.sh
        """)
    )

    (benchmark_dir / "powerfit_many.sh").write_text(
        dedent("""\
        #!/bin/bash
        set -euxo pipefail
        #SBATCH --nodes=1
        #SBATCH --ntasks-per-node=1
        #SBATCH --cpus-per-task=1
        #SBATCH --partition=gpu

        # Make progressbar less chatty
        export TQDM_MININTERVAL=9

        . ../.venv/bin/activate
        find work -name powerfit.sh -execdir bash {} \\;
        """)
    )

    print(  # noqa: T201
        dedent("""\
        To run all remote.sh (search and retrieve) scripts:

            sbatch remote_many.sh

        To run all filter.sh scripts:

            sbatch filter_many.sh

        To run all powerfit.sh scripts:

            sbatch powerfit_many.sh
        """)
    )


if __name__ == "__main__":
    main()
