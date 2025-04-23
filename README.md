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