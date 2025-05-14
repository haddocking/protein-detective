# protein-detective

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

### AlphaFold protein structure database api client

The client was generated using

```shell
uvx openapi-generator-cli generate \
  -i https://alphafold.ebi.ac.uk/api/openapi.json \
  --skip-validate-spec \
  -g python \
  -o ./alphafold_client \
  --package-name protein_detective.alphafold_client \
  --additional-properties=generateSourceCodeOnly=true,disallowAdditionalPropertiesIfNotPresent=true,library=asyncio
# Treat alphafold client as a submodule of the protein-detective package
mkdir -p src/protein_detective/alphafold_client
mv alphafold_client/protein_detective/alphafold_client/*.py src/protein_detective/alphafold_client/
mv alphafold_client/protein_detective/alphafold_client/api src/protein_detective/alphafold_client/
mv alphafold_client/protein_detective/alphafold_client/models src/protein_detective/alphafold_client/
rm -rf alphafold_client
```

Anytime the https://alphafold.ebi.ac.uk/api/openapi.json changes, the client code should be regenerated.
