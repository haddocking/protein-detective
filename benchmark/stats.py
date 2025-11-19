from pathlib import Path
from os import listdir

from pdconfig import datasets


def nr_files_in_directory(path: Path) -> int:
    return len(listdir(path))


def dataset_stats(path: Path):
       nr_af_downloads = nr_files_in_directory(path / "downloads" / "alphafold")
       nr_pdb_downloads = nr_files_in_directory(path / "downloads" / "pdbe")
       nr_pdb_chain_filtered = nr_files_in_directory(path / "pdb_chain_filtered")
       nr_filtered = nr_files_in_directory(path / "filtered")

for dataset in datasets:
        output_dir = dataset.output_dir
        