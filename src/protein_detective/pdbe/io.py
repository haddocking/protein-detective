import logging
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import atomium
from tqdm import tqdm

logger = logging.getLogger(__name__)


@dataclass
class ChainsPositions:
    chains: list[str]
    start: int
    end: int


def parse_uniprot_chain(uniprot_chain: str) -> ChainsPositions:
    """
    Parse a chain string as returned from a Uniprot SPARQL query.

    Args:
        chain: A string in the format "B/D=1-81".

    Returns:
        A tuple containing a set of chains and the start and end positions.
    """
    parts = uniprot_chain.split("=")
    chains = parts[0].split("/")
    if len(chains) == 0:
        msg = f"Missing chains in {uniprot_chain}"
        raise ValueError(msg)
    start, end = map(int, parts[1].split("-"))
    return ChainsPositions(chains=chains, start=start, end=end)


def write_single_chain_pdb_file(
    pdb_file: Path | str, uniprot_chain: str, output_file: Path | str, out_chain: str = "A"
) -> None:
    """Saves a specific protein chain from a PDB file to a new PDB file.

    Args:
        pdb_file: Path to the input PDB file.
        uniprot_chain: UniProt chain identifier (e.g., "B/D=1-81").
        output_file: Path to the output PDB file.
        out_chain: Chain identifier for the saved chain in the output file..
    """
    protein_chain = parse_uniprot_chain(uniprot_chain)
    chain2keep = protein_chain.chains[0]
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
        uniprot_chain = proteinpdb.chain
        uniprot_acc = proteinpdb.uniprot_acc
        output_file = single_chain_dir / f"{uniprot_acc}_{pdb_file.stem}.pdb"
        if output_file.exists():
            logger.info(
                f"Output file {output_file} already exists. Skipping saving single chain PDB file for {pdb_file}.",
            )
            continue
        write_single_chain_pdb_file(pdb_file, uniprot_chain, output_file)
        yield SingleChainResult(
            uniprot_acc=uniprot_acc,
            pdb_id=proteinpdb.id,
            output_file=output_file,
        )
