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


def filter_and_write_single_chain_pdb_file(
    mmcif_file: Path | str,
    chain2keep: str,
    output_file: Path | str,
    min_residues: int,
    max_residues: int,
    out_chain: str = "A",
) -> tuple[bool, int]:
    """Saves a specific protein chain from a mmCIF file to a new PDB file.

    Args:
        mmcif_file: Path to the input mmCIF file.
        chain2keep: Chain to keep.
        output_file: Path to the output PDB file.
        min_residues: Minimum number of residues in the chain to write.
        max_residues: Maximum number of residues in the chain to write.
        out_chain: Chain identifier for the saved chain in the output file.

    Returns:
        A tuple containing a boolean indicating whether
        chain is in the residue range and the file was written successfully,
        and the number of residues in the chain.
    """
    pdb = atomium.open(str(mmcif_file))
    chain: atomium.Chain = pdb.model.chain(chain2keep)  # type: ignore[missing-attribute]
    nr_residues = len(chain)
    if nr_residues < min_residues:
        logger.info(
            "Skipping %s, because it has too few residues in chain %s: %d < %d.",
            mmcif_file,
            chain2keep,
            nr_residues,
            min_residues,
        )
        return False, nr_residues
    if nr_residues > max_residues:
        logger.info(
            "Skipping %s, because it has too many residues in chain %s: %d > %d.",
            mmcif_file,
            chain2keep,
            nr_residues,
            max_residues,
        )
        return False, nr_residues
    logger.info(
        'From %s taking chain "%s", with %d residues and saving as "%s" with chain %s.',
        mmcif_file,
        chain2keep,
        nr_residues,
        output_file,
        out_chain,
    )
    # pyrefly: ignore  # noqa: ERA001
    chain.copy(out_chain).save(
        str(output_file),
    )
    # TODO use less diskspace, save gzipped and make powerfit work with it
    return True, nr_residues


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
class SingleChainQuery:
    """Query for writing single chain PDB files.

    Parameters:
        min_residues: Minimum number of residues that must be in chain.
        max_residues: Maximum number of residues that must be in chain.
    """

    min_residues: int
    max_residues: int


@dataclass(frozen=True)
class SingleChainResult:
    """Result of writing a single chain PDB file.

    Parameters:
        uniprot_acc: The UniProt accession.
        pdb_id: The PDB ID of the entry.
        output_file: The path to the output PDB file with
            just the first chain (renamed to A) belonging to given Uniprot accession.
            Only set when passed is True.
        nr_residues: The number of residues in the chain that was written.
        passed: Whether the chain passed the number of residue filter.
    """

    uniprot_acc: str
    pdb_id: str
    output_file: Path | None
    nr_residues: int
    passed: bool


def nr_residues_in_chain(file: Path | str, chain: str = "A") -> int:
    """Returns the number of residues in a specific chain from a mmCIF/pdb file.

    Args:
        file: Path to the input mmCIF/pdb file.
        chain: Chain to keep.

    Returns:
        The number of residues in the specified chain.
    """
    pdb = atomium.open(str(file))
    chain: atomium.Chain = pdb.model.chain(chain)  # type: ignore[missing-attribute]
    return len(chain)


def write_single_chain_pdb_file(
    proteinpdb: ProteinPdbRow,
    session_dir: Path,
    single_chain_dir: Path,
    query: SingleChainQuery,
) -> SingleChainResult:
    """Process a ProteinPdbRow to write a single chain PDB file if possible, returning the result.

    Args:
        proteinpdb: A ProteinPdbRow object.
        session_dir: The directory where the session files are stored.
        single_chain_dir: The directory where the single chain PDB files will be saved.
        query: The query containing the minimum and maximum number of residues.

    Returns:
        Result object containing the output file path and whether the chain passed the residue filter.
    """
    if not proteinpdb.mmcif_file:
        logger.warning(
            "Skipping %s, because it does not have a file.",
            proteinpdb.id,
        )
        return SingleChainResult(
            uniprot_acc=proteinpdb.uniprot_acc,
            pdb_id=proteinpdb.id,
            output_file=None,
            nr_residues=0,
            passed=False,
        )

    mmcif_file = proteinpdb.mmcif_file
    chain2keep = first_chain_from_uniprot_chains(proteinpdb.uniprot_chains)
    uniprot_acc = proteinpdb.uniprot_acc
    output_file = single_chain_dir / f"{uniprot_acc}_{mmcif_file.stem}_{chain2keep}2A.pdb"

    if output_file.exists():
        logger.info(
            f"Output file {output_file} already exists. Skipping saving single chain PDB file for {mmcif_file}.",
        )
        nr_residues = nr_residues_in_chain(output_file)
        passed = True
    else:
        passed, nr_residues = filter_and_write_single_chain_pdb_file(
            mmcif_file=mmcif_file,
            chain2keep=chain2keep,
            output_file=output_file,
            min_residues=query.min_residues,
            max_residues=query.max_residues,
        )

    real_output_file = None
    if passed:
        real_output_file = output_file.relative_to(session_dir)
    return SingleChainResult(
        uniprot_acc=uniprot_acc,
        pdb_id=proteinpdb.id,
        output_file=real_output_file,
        nr_residues=nr_residues,
        passed=passed,
    )


def write_single_chain_pdb_files(
    proteinpdbs: list[ProteinPdbRow], session_dir: Path, single_chain_dir: Path, query: SingleChainQuery
) -> Generator[SingleChainResult]:
    """Writes single chain PDB files from the provided protein PDB rows.

    Args:
        proteinpdbs: A list of ProteinPdbRow objects.
        session_dir: The directory where the session files are stored.
        single_chain_dir: The directory where the single chain PDB files will be saved.
        query: The query containing the minimum and maximum number of residues.

    Yields:
        SingleChainResult objects containing the output file path and whether the chain passed the residue filter.
    """
    for proteinpdb in tqdm(proteinpdbs, desc="Saving single chain PDB files from PDBe"):
        yield write_single_chain_pdb_file(proteinpdb, session_dir, single_chain_dir, query)
