 <!-- --8<-- [start:mkdocindex] -->
# protein-detective

[![Documentation](https://img.shields.io/badge/Documentation-bonvinlab.org-blue?style=flat-square&logo=gitbook)](https://www.bonvinlab.org/protein-detective/)
[![CI](https://github.com/haddocking/protein-detective/actions/workflows/ci.yml/badge.svg)](https://github.com/haddocking/protein-detective/actions/workflows/ci.yml)
[![Research Software Directory Badge](https://img.shields.io/badge/rsd-00a3e3.svg)](https://www.research-software.nl/software/protein-detective)
<!-- [![PyPI](https://img.shields.io/pypi/v/protein-detective)](https://pypi.org/project/protein-detective/) -->

Python package to detect proteins in EM density maps.

## Install

```shell
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
# GO:0005634 == Nucleus
# GO:0003677 == DNA binding
```

In `./mysession` directory, you will find session.db file, which is a [DuckDB](https://duckdb.org/) database with search results.

### To retrieve a bunch of structures

```shell
protein-detective retrieve ./mysession
```

In `./mysession` directory, you will find PDB files from PDBe and AlphaFold DB.

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

<!-- --8<-- [end:mkdocindex] -->

## Develop

This package uses [uv](https://docs.astral.sh/uv) to manage its development environment.

```shell
uv pip install -e .
```

To work on notebooks in docs/ directory

```shell
uv sync --group docs
# Open a notebook with VS code and select .venv/bin/python as kernel
```

To run the tests

```shell
uv run pytest
```

To format the code

```shell
uvx ruff format
# Sort imports with
uvx ruff check --select I --fix
```

To lint the code

```shell
uvx ruff check
```
(Use `uvx ruff check --fix` to fix the issues automatically)


To type check with [pyrefly](https://pyrefly.org/) the code

```shell
uv run pyrefly check
```

<details>
<summary>To type check with pyrefly the notebooks</summary>

Pyrefly does not support notebooks yet, so we need to convert them to python scripts and then run pyrefly on them.

```shell
uv run --group docs jupyter nbconvert --to python docs/*.ipynb
# Comment out magic commands
sed -i 's/^get_ipython/# get_ipython/' docs/*.py
uv run pyrefly check docs/*.py
rm docs/*.py
```

</details>

### Documentation

Start the live-reloading docs server with

```shell
uv run mkdocs serve
```
Build the documentation site with

```shell
uv run mkdocs build
# The site will be built in the `site/` directory.
# You can preview it with
python3 -m http.server -d site
```
