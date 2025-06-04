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
    pdb_file: Path | str, chain2keep: str, output_file: Path | str, out_chain: str = "A"
) -> None:
    """Saves a specific protein chain from a PDB file to a new PDB file.

    Args:
        pdb_file: Path to the input PDB file.
        chain2keep: Chain to keep.
        output_file: Path to the output PDB file.
        out_chain: Chain identifier for the saved chain in the output file..
    """
    logger.info(
        'From %s taking chain "%s" and saving as "%s" with chain %s.', pdb_file, chain2keep, output_file, out_chain
    )
    pdb = atomium.open(str(pdb_file))
    # pyrefly: ignore  # noqa: ERA001
    pdb.model.chain(chain2keep).copy(out_chain).save(
        str(output_file),
    )
    # TODO use less diskspace, save gzipped and make powerfit work with it


@dataclass(frozen=True)
class ProteinPdbRow:
    id: str
    chain: str
    uniprot_acc: str
    pdb_file: Path


@dataclass(frozen=True)
class SingleChainResult:
    uniprot_acc: str
    pdb_id: str
    output_file: Path


def write_single_chain_pdb_files(
    proteinpdbs: list[ProteinPdbRow],
    single_chain_dir: Path,
) -> Generator[SingleChainResult]:
    for proteinpdb in tqdm(proteinpdbs, desc="Saving single chain PDB files from PDBe"):
        pdb_file = proteinpdb.pdb_file
        uniprot_chains = proteinpdb.chain
        chain2keep = first_chain_from_uniprot_chains(uniprot_chains)
        uniprot_acc = proteinpdb.uniprot_acc
        output_file = single_chain_dir / f"{uniprot_acc}_{pdb_file.stem}_{chain2keep}2A.pdb"
        if output_file.exists():
            logger.info(
                f"Output file {output_file} already exists. Skipping saving single chain PDB file for {pdb_file}.",
            )
            continue
        write_single_chain_pdb_file(pdb_file, chain2keep, output_file)
        yield SingleChainResult(
            uniprot_acc=uniprot_acc,
            pdb_id=proteinpdb.id,
            output_file=output_file,
        )
