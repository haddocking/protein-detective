"""
Trying to figure out why in slurm log I see:
```
+ ls -1 downloads/pdbe/6wuc.cif.gz
ls: cannot access 'downloads/pdbe/6wuc.cif.gz': No such file or directory
```


"""

import csv
from pathlib import Path

from pdconfig import datasets, root_work_dir
from protein_quest.cli import _write_pdbe_csv
from protein_quest.uniprot import search4pdb

pdb_results_fn = Path("pdb_results.csv")
if not pdb_results_fn.exists():
    uniprot_accs = [d.Uniprot_id for d in datasets]
    pdb_results = search4pdb(uniprot_accs, batch_size=50, limit=40_000)
    with pdb_results_fn.open("w", encoding="utf-8") as f:
        _write_pdbe_csv(f, pdb_results)
with pdb_results_fn.open("r", encoding="utf-8") as f:
    r = csv.DictReader(f)
    pdb_results = list(r)

print(  # noqa: T201
    ",".join(
        [
            "output_dir",
            "Number_of_residues_modelled",
            "Number_of_residues_in_uniprot",
            "Number_of_residues_in_construct",
            "PDB_chain_length",
            "max_residues",
            "discarded",
        ]
    )
)
for dataset in datasets:
    filtered_dir = dataset.output_dir / "filtered"
    if filtered_dir.exists():
        continue

    sorf_res_range_fraction = 0.5
    soft_max_res = int(float(dataset.Number_of_residues_modelled) * (1 + sorf_res_range_fraction))
    pdb_chain_length = next(
        int(r["chain_length"])
        for r in pdb_results
        if r["uniprot_accession"] == dataset.Uniprot_id and r["pdb_id"] == dataset.PDB_id
    )
    discarded = pdb_chain_length > soft_max_res
    if not discarded:
        continue

    print(  # noqa: T201
        ",".join(
            [
                str(dataset.output_dir.relative_to(root_work_dir)),
                str(dataset.Number_of_residues_modelled),
                str(dataset.Number_of_residues_in_uniprot),
                str(dataset.Number_of_residues_in_construct),
                str(pdb_chain_length),
                str(soft_max_res),
                str(discarded),
            ]
        )
    )
