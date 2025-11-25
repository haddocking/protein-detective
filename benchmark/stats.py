"""Script to print some statistics about the (partially) completed datasets."""
# ruff: noqa: T201 this is a script
from os import listdir
from pathlib import Path

from pdconfig import datasets


def nr_files_in_directory(path: Path) -> int:
    try:
        return len(listdir(path))  # noqa: PTH208
    except FileNotFoundError:
        return 0


def dataset_stats_of_dirs(path: Path) -> dict[str, int]:
    nr_af_downloads = nr_files_in_directory(path / "downloads" / "alphafold")
    nr_pdb_downloads = nr_files_in_directory(path / "downloads" / "pdbe")
    nr_pdb_chain_filtered = nr_files_in_directory(path / "pdb_chain_filtered")
    nr_filtered = nr_files_in_directory(path / "filtered")
    return {
        "nr_af_downloads": nr_af_downloads,
        "nr_pdb_downloads": nr_pdb_downloads,
        "nr_pdb_chain_filtered": nr_pdb_chain_filtered,
        "nr_filtered": nr_filtered,
    }


# TODO add stats for powerfit, show top 5 fits (uniprot acc+pdb id) per dataset

for dataset in datasets:
    output_dir = dataset.output_dir
    print(f"Stats for {output_dir.parent.name}/{output_dir.name}:")
    stats = dataset_stats_of_dirs(output_dir)
    for key, value in stats.items():
        print(f"  {key}: {value}")
