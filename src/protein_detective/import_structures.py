from pathlib import Path
from typing import Annotated

from cyclopts import Parameter, validators
from protein_quest.structure.chains import chains_in_structure
from protein_quest.structure.convert import convert_to_cif_file
from protein_quest.structure.files import glob_structure_files
from protein_quest.structure.formats import read_structure
from protein_quest.structure.uniprot import structure2uniprot_accessions
from protein_quest.utils import CopyMethod
from rich.progress import track

from protein_detective.common_cli import Common, console


def import_structures(
    structures_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True, exists=True))],
    session_dir: Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=True))],
    /,
    *,
    copy_method: CopyMethod = "hardlink",
    strict: Annotated[bool, Parameter(negative="")] = False,
    _: Common | None = None,
):
    """Import structures from a file or directory.

    Args:
        structures_dir: Directory containing structure files to import
        session_dir: Session directory to store results
        copy_method: Method to use for importing files. If 'copy', files will be copied. If
            'symlink', symbolic links will be created. If 'hardlink', hard links will be created
            (unavailable on Windows).
        strict: Raise an error if structure files do not meet expected criteria (single chain A, single
            UniProt accession). Without this flag, files that do not meet these criteria are skipped with
            a warning.
    """
    import_dir: Path = session_dir / "imported_structures"
    import_dir.mkdir(exist_ok=True, parents=True)

    imported_files = []
    for structure_file in track(
        glob_structure_files(structures_dir), description="Importing structures...", console=console
    ):
        conversion_stats = convert_to_cif_file(
            structure_file.resolve(), import_dir, copy_method=copy_method, output_format=".cif.gz"
        )
        output_file = conversion_stats.output_file
        imported_files.append(output_file)
        structure = read_structure(output_file)
        chains = chains_in_structure(structure)
        chain_ids = {chain.name for chain in chains}
        if chain_ids != {"A"}:
            msg = f"Structure file {structure_file} contains chains {chain_ids}, expected single chain A."
            msg += " Use `protein-quest filter chain` to fix this."
            if strict:
                raise ValueError(msg)
            console.print(f"Warning: {msg} Skipping file.", style="yellow")
            output_file.unlink()
            continue
        uniprot_accessions = structure2uniprot_accessions(structure)
        if len(uniprot_accessions) != 1:
            msg = f"Structure file {structure_file} contains {uniprot_accessions} UniProt accessions, expected 1."
            msg += " Use `protein-quest convert structures --uniprots ...` to fix the UniProt accessions."
            if strict:
                raise ValueError(msg)
            console.print(f"Warning: {msg} Skipping file.", style="yellow")
            output_file.unlink()
            continue

    # TODO write uniprot.txt
    # TODO write alphafold.csv
    # TODO write pdbe.csv
    # TODO for structures without resolution, fetch pdbe-quality reports
    # and write pdbe-quality.json. It will require network access.
    # Should this be toggled by a flag or just documented?
    # TODO Write RO crate with imported_files as output_files

    # TODO downstream commands should look if import_dir exists and if so, use it as input for powerfit.
    # TODO determine if imported structures can be filtered with filter command.
