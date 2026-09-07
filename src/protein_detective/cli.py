"""CLI entry point for protein-detective."""

import cyclopts
from cyclopts import App, Group
from rich.traceback import install as install_rich_traceback

from protein_detective.__version__ import __version__
from protein_detective.common_cli import console
from protein_detective.filter import run_filter
from protein_detective.import_structures import import_structures
from protein_detective.meta import create_meta_duckdb
from protein_detective.powerfit.cli import powerfit_app
from protein_detective.refine import refine_with_haddock3
from protein_detective.retrieve import retrieve
from protein_detective.search import search

workflow_group = Group("Workflow", sort_key=0)
utilities_group = Group("Utilities", sort_key=1)

app = App(
    name="protein-detective",
    version=__version__,
    help="Protein Detective CLI",
    group_commands=utilities_group,
)

app.register_install_completion_command(group=utilities_group, sort_key=2)
install_rich_traceback(console=console, suppress=[cyclopts])

app.command(search, group=workflow_group, sort_key=0)
app.command(retrieve, group=workflow_group, sort_key=1)
app.command(run_filter, name="filter", group=workflow_group, sort_key=2)
powerfit_app.group = workflow_group
powerfit_app.sort_key = 4
app.command(powerfit_app)
app.command(refine_with_haddock3, name="refine", group=workflow_group, sort_key=5)
app.command(import_structures, group=utilities_group, sort_key=1)
app.command(create_meta_duckdb, name="meta", group=utilities_group, sort_key=0)
