"""CLI entry point for protein-detective."""

import cyclopts
from cyclopts import App
from rich.traceback import install as install_rich_traceback

from protein_detective.__version__ import __version__
from protein_detective.common_cli import console
from protein_detective.filter import run_filter
from protein_detective.import_structures import import_structures
from protein_detective.powerfit.cli import powerfit_app
from protein_detective.refine import refine_with_haddock3
from protein_detective.retrieve import retrieve
from protein_detective.search import search

app = App(
    name="protein-detective",
    version=__version__,
    help="Protein Detective CLI",
)

app.register_install_completion_command()
install_rich_traceback(console=console, suppress=[cyclopts])

# TODO Move non-powerfit commands under `protein-detective candidates` subcommand?
app.command(search)
app.command(retrieve)
app.command(run_filter, name="filter")
app.command(powerfit_app)
app.command(import_structures)
app.command(refine_with_haddock3, name="refine")