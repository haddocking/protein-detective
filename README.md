# protein-detective

[![Documentation](https://img.shields.io/badge/Documentation-bonvinlab.org-blue?style=flat-square&logo=gitbook)](https://www.bonvinlab.org/protein-detective/)
[![CI](https://github.com/haddocking/protein-detective/actions/workflows/ci.yml/badge.svg)](https://github.com/haddocking/protein-detective/actions/workflows/ci.yml)
[![Research Software Directory Badge](https://img.shields.io/badge/rsd-00a3e3.svg)](https://www.research-software.nl/software/protein-detective)
[![PyPI](https://img.shields.io/pypi/v/protein-detective)](https://pypi.org/project/protein-detective/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.15632658.svg)](https://doi.org/10.5281/zenodo.15632658)

Python package to detect proteins in EM density maps.

## Install

```shell
pip install protein-detective
```

Or to use the latest development version:
```
pip install git+https://github.com/haddocking/protein-detective.git
```

## Usage

### Search Uniprot for structures

```shell
protein-detective search \
    --taxon-id 9606 \
    --reviewed \
    --subcellular-location-uniprot nucleus \
    --subcellular-location-go GO:0005634 \
    --molecular-function-go GO:0003677 \
    --limit 100 \
    ./mysession
```
([GO:0005634](https://www.ebi.ac.uk/QuickGO/term/GO:0005634) is "Nucleus" and [GO:0003677](https://www.ebi.ac.uk/QuickGO/term/GO:0003677) is  "DNA binding")

In `./mysession` directory, you will find session.db file, which is a [DuckDB](https://duckdb.org/) database with search results.

### To retrieve a bunch of structures

```shell
protein-detective retrieve ./mysession
```

In `./mysession` directory, you will find mmCIF files from PDBe and PDB files and AlphaFold DB.

### To filter AlphaFold structures on confidence

Filter AlphaFoldDB structures based on density confidence.
Keeps entries with requested number of residues which have a confidence score above the threshold.
Also writes pdb files with only those residues.

```shell
protein-detective density-filter \
    --confidence-threshold 50 \
    --min-residues 100 \
    --max-residues 1000 \
    ./mysession
```

### To prune PDBe files

Make PDBe files smaller by only keeping first chain of found uniprot entry and renaming to chain A.

```shell
protein-detective prune-pdbs ./mysession
```

### Powerfit

Generate the powerfit commands for the filtered and pruned structures.

```shell
protein-detective powerfit commands ../powerfit-tutorial/ribosome-KsgA.map 13 docs/session1 
```
This will print commands to the terminal, which you can then run in whatever way you prefer.
Like just sequentially, or with [GNU parallel](https://www.gnu.org/software/parallel/) or as a [Slurm array job](https://slurm.schedmd.com/job_array.html).


To print top 10 solutions to the terminal, you can use:

```shell
protein-detective powerfit report docs/session1
```

## Contributing

For development information and contribution guidelines, please see [CONTRIBUTING.md](CONTRIBUTING.md).
