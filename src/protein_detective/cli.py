"""CLI entry point for protein-detective."""

import cyclopts
from cyclopts import App
from rich.console import Console
from rich.traceback import install as install_rich_traceback

from protein_detective.__version__ import __version__
from protein_detective.retrieve import retrieve
from protein_detective.search import search

console = Console(stderr=True)
rprint = console.print

app = App(
    name="protein-detective",
    version=__version__,
    help="Protein Detective CLI",
)

app.register_install_completion_command()
install_rich_traceback(console=console, suppress=[cyclopts])

app.command(search)
app.command(retrieve)
