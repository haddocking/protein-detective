# protein-detective

## Install

```shell
pip install git+https://github.com/haddocking/protein-detective.git
```

## Usage

To retrieve a bunch of structures

```shell
protein-detective retrieve \
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
In `./mysession` directory, you will find 
- PDB files from PDBe and AlphaFold DB
- predicted alignment error (pae) files from AlphaFold DB
- session.db - a duckdb database with the metadata of the structures

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
```

To lint the code

```shell
uvx ruff check
```
