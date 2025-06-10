"""MkDocs hooks for generating CLI documentation."""

import argparse
import io
import logging
from pathlib import Path

from protein_detective.cli import make_parser

logger = logging.getLogger("mkdocs.plugins.argparse")


def generate_cli_docs() -> str:
    """Generate CLI documentation markdown."""
    parser = make_parser()

    # Capture main help
    help_output = io.StringIO()
    parser.print_help(help_output)
    main_help = help_output.getvalue()

    # Start building markdown
    markdown_lines = [
        "# CLI Reference\n",
        "Documentation for the `protein-detective` CLI commands.\n",
        "## Main Command\n",
        "```shell",
        "protein-detective --help",
        main_help,
        "```\n## Subcommands\n",
    ]

    # Get subcommands and their help
    subparsers_actions = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]

    if subparsers_actions:
        subparsers_action = subparsers_actions[0]
        for sub_command, subparser in subparsers_action.choices.items():
            # Capture subcommand help
            help_output = io.StringIO()
            subparser.print_help(help_output)
            subcommand_help = help_output.getvalue()

            markdown_lines.extend(
                [
                    f"### {sub_command}\n",
                    "```shell",
                    f"$ protein-detective {sub_command} --help",
                    subcommand_help,
                    "```\n",
                ]
            )

    return "\n".join(markdown_lines)


def on_pre_build(**_kwargs):
    """Generate CLI documentation before building the docs."""
    docs_content = generate_cli_docs()

    # Check if content has changed before writing
    docs_dir = Path(__file__).parent
    cli_md_path = docs_dir / "cli.md"

    # Only write if content is different to avoid rebuild loops
    if not cli_md_path.exists() or cli_md_path.read_text() != docs_content:
        cli_md_path.write_text(docs_content)
        logger.info("CLI documentation generated/updated successfully")
    else:
        logger.info("CLI documentation unchanged, skipping write")
