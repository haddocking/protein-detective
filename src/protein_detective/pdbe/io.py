import logging
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import atomium
from tqdm import tqdm

logger = logging.getLogger(__name__)


def first_chain_from_uniprot_chains(uniprot_chains: str) -> str:
    """Extracts the first chain identifier from a UniProt chains string.

    The UniProt chains string is formatted (with EBNF notation) as follows:

        chain_group(=range)?(,chain_group(=range)?)*

    where:
        chain_group := chain_id(/chain_id)*
        chain_id    := [A-Za-z]+
        range       := start-end
        start, end  := integer

    Args:
        uniprot_chains: A string representing UniProt chains, For example "B/D=1-81".
    Returns:
        The first chain identifier from the UniProt chain string. For example "B".
    """
    chains = uniprot_chains.split("=")
    parts = chains[0].split("/")
    return parts[0]


def write_single_chain_pdb_file(
    mmcif_file: Path | str, chain2keep: str, output_file: Path | str, out_chain: str = "A"
) -> None:
    """Saves a specific protein chain from a mmCIF file to a new PDB file.

    Args:
        mmcif_file: Path to the input mmCIF file.
        chain2keep: Chain to keep.
        output_file: Path to the output PDB file.
        out_chain: Chain identifier for the saved chain in the output file..
    """
    logger.info(
        'From %s taking chain "%s" and saving as "%s" with chain %s.', mmcif_file, chain2keep, output_file, out_chain
    )
    pdb = atomium.open(str(mmcif_file))
    # pyrefly: ignore  # noqa: ERA001
    pdb.model.chain(chain2keep).copy(out_chain).save(
        str(output_file),
    )
    # TODO use less diskspace, save gzipped and make powerfit work with it


@dataclass(frozen=True)
class ProteinPdbRow:
    """Info about PDB entry and its relation to an Uniprot entry

    Parameters:
        id: The PDB ID of the entry.
        uniprot_chains: The UniProt chains associated with the PDB entry.
        uniprot_acc: The UniProt accession number associated with the PDB entry.
        mmcif_file: The path to the mmCIF file for the PDB entry, or None if not retrieved yet.
    """

    id: str
    uniprot_chains: str
    uniprot_acc: str
    mmcif_file: Path | None


@dataclass(frozen=True)
class SingleChainResult:
    """Result of writing a single chain PDB file.

    Parameters:
        uniprot_acc: The UniProt accession.
        pdb_id: The PDB ID of the entry.
        output_file: The path to the output PDB file with
            just the first chain (renamed to A) belonging to given Uniprot accession.
    """

    uniprot_acc: str
    pdb_id: str
    output_file: Path


def write_single_chain_pdb_files(
    proteinpdbs: list[ProteinPdbRow],
    session_dir: Path,
    single_chain_dir: Path,
) -> Generator[SingleChainResult]:
    """Writes single chain PDB files from the provided protein PDB rows.

    Args:
        proteinpdbs: A list of ProteinPdbRow objects.
        session_dir: The directory where the session files are stored.
        single_chain_dir: The directory where the single chain PDB files will be saved.

    Yields:
        SingleChainResult objects containing the UniProt accession, PDB ID, and output file path.
    """
    for proteinpdb in tqdm(proteinpdbs, desc="Saving single chain PDB files from PDBe"):
        if not proteinpdb.mmcif_file:
            logger.warning(
                "Skipping %s, because it does not have a file.",
                proteinpdb.id,
            )
            continue
        mmcif_file = session_dir / proteinpdb.mmcif_file
        uniprot_chains = proteinpdb.uniprot_chains
        chain2keep = first_chain_from_uniprot_chains(uniprot_chains)
        uniprot_acc = proteinpdb.uniprot_acc
        output_file = single_chain_dir / f"{uniprot_acc}_{mmcif_file.stem}_{chain2keep}2A.pdb"
        if output_file.exists():
            logger.info(
                f"Output file {output_file} already exists. Skipping saving single chain PDB file for {mmcif_file}.",
            )
            yield SingleChainResult(
                uniprot_acc=uniprot_acc,
                pdb_id=proteinpdb.id,
                output_file=output_file.relative_to(session_dir),
            )
            continue
        write_single_chain_pdb_file(mmcif_file, chain2keep, output_file)
        yield SingleChainResult(
            uniprot_acc=uniprot_acc,
            pdb_id=proteinpdb.id,
            output_file=output_file.relative_to(session_dir),
        )
