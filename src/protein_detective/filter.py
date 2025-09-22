"""Module dealing with filtering of protein structures.

In protein_quest package the filters are more granular, here we combine them into coarse grained methods.
"""

import gzip
import logging
import shutil
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from distributed.deploy.cluster import Cluster
from protein_quest.alphafold.confidence import ConfidenceFilterQuery, ConfidenceFilterResult, filter_files_on_confidence
from protein_quest.alphafold.fetch import AlphaFoldEntry
from protein_quest.filters import (
    ChainFilterStatistics,
    ResidueFilterStatistics,
    filter_files_on_chain,
    filter_files_on_residues,
)
from protein_quest.ss import (
    SecondaryStructureFilterQuery,
    SecondaryStructureFilterResult,
    filter_files_on_secondary_structure,
)
from protein_quest.utils import copyfile

if TYPE_CHECKING:
    from protein_detective.db import ProteinPdbRow
else:
    ProteinPdbRow = object  # pragma: no cover

logger = logging.getLogger(__name__)


@dataclass
class FilterOptions:
    """Filter query containing confidence and secondary structure filters.

    Parameters:
        confidence: The confidence filter query.
        secondary_structure: The secondary structure filter query.
    """

    confidence: ConfidenceFilterQuery
    secondary_structure: SecondaryStructureFilterQuery


@dataclass
class FilteredStructure:
    """Filter result of a single uniprot+[pdb] entry.

    Parameters:
        uniprot_accession: The UniProt accession.
        pdb_id: The PDB ID if applicable.
        confidence: The confidence filter result if applicable.
        chain: The chain filter result if applicable.
        residue: The residue filter result if applicable.
        secondary_structure: A tuple containing:
            - The input file path for the secondary structure filter.
            - The secondary structure filter result.
            - The output file path for the secondary structure filter, if passed.
    """

    uniprot_accession: str
    pdb_id: str | None = None
    confidence: ConfidenceFilterResult | None = None
    chain: ChainFilterStatistics | None = None
    residue: ResidueFilterStatistics | None = None
    secondary_structure: tuple[Path, SecondaryStructureFilterResult, Path | None] | None = None

    @property
    def passed(self) -> bool:
        """Whether the structure passed all filters."""
        if self.secondary_structure is not None and not self.secondary_structure[1].passed:
            return False
        if self.residue is not None and not self.residue.passed:
            return False
        if self.chain is not None and not self.chain.passed:
            return False
        if self.confidence is not None and self.confidence.filtered_file is None:  # noqa: SIM103 -- use same logic as in output_file property
            return False
        return True

    @property
    def output_file(self) -> Path | None:
        """Get the output file of the last filter that was applied

        Only valid if the structure passed all filters.
        """
        if self.passed:
            if self.secondary_structure is not None and self.secondary_structure[2] is not None:
                return self.secondary_structure[2]
            if self.residue is not None and self.residue.output_file is not None:
                return self.residue.output_file
            if self.chain is not None and self.chain.output_file is not None:
                return self.chain.output_file
            if self.confidence is not None and self.confidence.filtered_file is not None:
                return self.confidence.filtered_file
        return None

    @output_file.setter
    def output_file(self, path: Path) -> None:
        """Set the output file of the last filter that was applied.

        Only valid if the structure passed all filters.
        """
        if self.passed:
            if self.secondary_structure is not None:
                p1, ssr, _ = self.secondary_structure
                self.secondary_structure = (p1, ssr, path)
            elif self.residue is not None:
                self.residue.output_file = path
            elif self.chain is not None:
                self.chain.output_file = path
            elif self.confidence is not None:
                self.confidence.filtered_file = path
        else:
            msg = "Cannot set output file for a structure that did not pass all filters."
            raise ValueError(msg)

    def make_relative_to(self, session_dir: Path) -> "FilteredStructure":
        """Make all file paths relative to the given session directory.

        Args:
            session_dir: The session directory to make paths relative to.

        Returns:
            A new FilterResultRow object with paths made relative to the session directory.
        """
        new_row = deepcopy(self)
        if new_row.confidence is not None and new_row.confidence.filtered_file is not None:
            new_row.confidence.filtered_file = new_row.confidence.filtered_file.relative_to(session_dir)
        if new_row.chain is not None and new_row.chain.output_file is not None:
            new_row.chain.output_file = new_row.chain.output_file.relative_to(session_dir)
        if new_row.residue is not None and new_row.residue.output_file is not None:
            new_row.residue.output_file = new_row.residue.output_file.relative_to(session_dir)
        if new_row.secondary_structure is not None:
            p1, ssr, p2 = new_row.secondary_structure
            p1 = p1.relative_to(session_dir)
            if p2 is not None:
                p2 = p2.relative_to(session_dir)
            new_row.secondary_structure = (p1, ssr, p2)
        return new_row


type FilterResults = dict[tuple[str, str | None], FilteredStructure]
"""Type alias for filter results mapping (uniprot_accession, pdb_id?) to FilteredStructure."""


def _filter_alphafolds_on_secondary_structure(
    secondary_structure: SecondaryStructureFilterQuery,
    cf_out_files: list[Path],
    final_dir: Path,
    af_total_results: FilterResults,
    alphafold_cif_files2upid: dict[str, tuple[str, None]],
):
    cf_ss_results = []
    logger.info("Filtering AlphaFold files on secondary structure")
    for cf_out_file, ss_result in filter_files_on_secondary_structure(cf_out_files, secondary_structure):
        ss_out_file: Path | None = None
        if ss_result.passed:
            ss_out_file = final_dir / cf_out_file.name
            if ss_out_file is None:
                raise ValueError
            copyfile(cf_out_file, ss_out_file, "symlink")
        cf_ss_results.append((cf_out_file, ss_result, ss_out_file))
        upid = alphafold_cif_files2upid[cf_out_file.name]
        if upid not in af_total_results:
            msg = f"Confidence filter result not found for {cf_out_file} aka {upid}"
            raise ValueError(msg)
        af_total_results[upid].secondary_structure = (cf_out_file, ss_result, ss_out_file)
    nr_ss_kept = len([r for r in cf_ss_results if r[2] is not None])
    logger.info("Kept %i files after secondary structure filtering in %s", nr_ss_kept, final_dir)


def filter_alphafold_structures(
    afs: list[AlphaFoldEntry], session_dir: Path, options: FilterOptions, final_dir: Path
) -> FilterResults:
    """Filter AlphaFold structures in the session directory based on confidence and secondary structure.

    Args:
        afs: The list of AlphaFold entries to filter.
        session_dir: The directory containing the session data, including AlphaFold structure files.
        options: The filter options containing confidence and secondary structure filter queries.
        final_dir: The directory to store the final filtered structures.

    Returns:
        A dictionary mapping (uniprot_accession, pdb_id) to FilteredStructure objects

    Raises:
        ValueError: If there are inconsistencies in the filtering results.
    """
    confidence = options.confidence
    secondary_structure = options.secondary_structure
    do_ss = secondary_structure.is_actionable()

    af_total_results: FilterResults = {}

    alphafold_cif_files = [e.cif_file for e in afs if e.cif_file is not None]
    alphafold_cif_files2upid = {e.cif_file.name: (e.uniprot_acc, None) for e in afs if e.cif_file is not None}

    logger.info("Filtering AlphaFold files on confidence")
    cf_dir = session_dir / "confidence_filtered" if do_ss else final_dir
    cf_dir.mkdir(parents=True, exist_ok=True)
    cf_result = list(filter_files_on_confidence(alphafold_cif_files, confidence, cf_dir, copy_method="symlink"))
    for e in cf_result:
        upid = alphafold_cif_files2upid[e.input_file]
        af_total_results[upid] = FilteredStructure(uniprot_accession=upid[0], confidence=e)
    cf_out_files = [e.filtered_file for e in cf_result if e.filtered_file is not None]
    nr_cf_kept = len(cf_out_files)
    logger.info("Kept %i files after confidence filtering in %s", nr_cf_kept, cf_dir)

    if nr_cf_kept > 0 and do_ss:
        _filter_alphafolds_on_secondary_structure(
            secondary_structure=secondary_structure,
            cf_out_files=cf_out_files,
            final_dir=final_dir,
            af_total_results=af_total_results,
            alphafold_cif_files2upid=alphafold_cif_files2upid,
        )
    return af_total_results


type FileNameChain2UniprotPdb = dict[tuple[str, str], tuple[str, str]]
"""Type alias for mapping (pdb_file_name, chain) to (uniprot_accession, pdb_id)."""


def _filter_pdb_structures_on_secondary_structure(
    final_dir: Path,
    secondary_structure: SecondaryStructureFilterQuery,
    pdbe_total_results: FilterResults,
    pc2upid: FileNameChain2UniprotPdb,
    do_pdb_residue: bool,
    chain_filtered: list[ChainFilterStatistics],
    chain_filtered_files: list[Path],
    residue_filtered: list[ResidueFilterStatistics],
    residue_filtered_files: list[Path],
):
    pdb_ss_in_files = residue_filtered_files if do_pdb_residue else chain_filtered_files
    pdb_chain_out_file2upid = {
        f.output_file: pc2upid[(f.input_file.name, f.chain_id)] for f in chain_filtered if f.output_file is not None
    }
    if do_pdb_residue:
        residue_in2residue_out = {f.input_file: f.output_file for f in residue_filtered if f.output_file is not None}
        pdb_chain_out_file2upid = {
            residue_in2residue_out[f]: upid
            for f, upid in pdb_chain_out_file2upid.items()
            if f in residue_in2residue_out
        }

    logger.info("Filtering %i PDBe files on secondary structure", len(pdb_ss_in_files))
    pdb_ss_results: list[tuple[Path, SecondaryStructureFilterResult, Path | None]] = []
    for input_file, result in filter_files_on_secondary_structure(
        file_paths=pdb_ss_in_files, query=secondary_structure
    ):
        output_file: Path | None = None
        upid = pdb_chain_out_file2upid[input_file]
        if upid not in pdbe_total_results:
            msg = f"Residue filter result not found for {input_file} aka {upid}"
            raise ValueError(msg)
        if result.passed:
            output_file = final_dir / input_file.name
            if output_file is None:
                raise ValueError
            copyfile(input_file, output_file, "symlink")
        pdbe_total_results[upid].secondary_structure = (input_file, result, output_file)
        pdb_ss_results.append((input_file, result, output_file))
    nr_pdb_ss_kept = len([r for r in pdb_ss_results if r[2] is not None])
    logger.info("Kept %i files after secondary structure filtering in %s", nr_pdb_ss_kept, final_dir)


def _filter_pdb_structures_by_residue_count(
    confidence: ConfidenceFilterQuery,
    chain_filtered_files: list[Path],
    chain_filtered: list[ChainFilterStatistics],
    output_dir: Path,
    pdbe_total_results: FilterResults,
    pc2upid: FileNameChain2UniprotPdb,
):
    logger.info("Filtering PDBe files on number of residues")
    residue_filtered = list(
        filter_files_on_residues(
            chain_filtered_files,
            output_dir,
            confidence.min_residues,
            confidence.max_residues,
            copy_method="symlink",
        )
    )
    input_file2residue_filtered = {f.input_file: f for f in residue_filtered}
    for f in chain_filtered:
        upid = pc2upid[(f.input_file.name, f.chain_id)]
        rc = pdbe_total_results[upid].chain
        if rc is None:
            msg = f"Chain filter result not found for {f.input_file} {f.chain_id}"
            raise ValueError(msg)
        rc_out = rc.output_file
        if rc_out is None:
            continue
        residue_out = input_file2residue_filtered[rc_out]
        pdbe_total_results[upid].residue = residue_out
    residue_filtered_files = [f.output_file for f in residue_filtered if f.output_file is not None]
    logger.info("Kept %i files after residue filtering in %s", len(residue_filtered_files), output_dir)
    return residue_filtered, residue_filtered_files


def _uncompress_gz_files(pdbe_total_results: FilterResults) -> None:
    # protein-quest downloaded and filtered *.cif.gz files however powerfit only understands *.pdb and *.cif files
    logger.info("Uncompressing *.cif.gz files to *.cif files")
    i = 0
    for r in pdbe_total_results.values():
        orig_output_file = r.output_file
        if orig_output_file is None or orig_output_file.suffix != ".gz":
            continue
        i += 1
        new_output_file = orig_output_file.with_suffix("")
        with gzip.open(orig_output_file, "rb") as f_in, new_output_file.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)  # pyright: ignore[reportArgumentType]
        orig_output_file.unlink()
        r.output_file = new_output_file
    logger.info("Uncompression of %i files complete", i)


def filter_pdbe_structures(
    proteinpdbs: list[ProteinPdbRow],
    session_dir: Path,
    options: FilterOptions,
    final_dir: Path,
    scheduler_address: str | Cluster | None,
) -> FilterResults:
    """Filter PDBe structures in the session directory based on chain, number of residues, and secondary structure.

    Also uncompresses any *.cif.gz files to *.cif files for use in powerfit.

    Args:
        proteinpdbs: The list of ProteinPdbRow entries to filter.
        session_dir: The directory containing the session data, including PDBe structure files.
        options: The filter options containing confidence and secondary structure filter queries.
        final_dir: The directory to store the final filtered structures.
        scheduler_address: Address of the Dask scheduler for distributed filtering. If None then local cluster is used.

    Returns:
        A dictionary mapping (uniprot_accession, pdb_id) to FilteredStructure objects
    """
    # In protein-quest we are just working with pdb files,
    # but in protein-detective we keep track which
    # pdb+chain belongs to which uniprot entry
    # so there is a lot of bookkeeping needed
    path2chains = {(p.mmcif_file, p.chain) for p in proteinpdbs if p.mmcif_file is not None}
    pc2upid: FileNameChain2UniprotPdb = {
        (p.mmcif_file.name, p.chain): (p.uniprot_acc, p.pdb_id) for p in proteinpdbs if p.mmcif_file is not None
    }

    confidence = options.confidence
    do_pdb_residue = not (confidence.min_residues == 0 and confidence.max_residues == sys.maxsize)
    secondary_structure = options.secondary_structure
    do_ss = secondary_structure.is_actionable()
    pdb_residue_dir = session_dir / "pdb_residue_filtered" if do_ss else final_dir
    pdb_residue_dir.mkdir(parents=True, exist_ok=True)
    pdb_chain_dir = session_dir / "pdb_chain_filtered"
    if not do_pdb_residue and not do_ss:
        pdb_chain_dir = final_dir
    pdb_chain_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Filtering PDBe files on chain of Uniprot to chain A")
    chain_filtered = filter_files_on_chain(
        path2chains, pdb_chain_dir, scheduler_address=scheduler_address, copy_method="symlink"
    )
    pdbe_total_results: FilterResults = {}
    for f in chain_filtered:
        # upid is tuple of uniprot_acc and pdb_id
        upid = pc2upid[(f.input_file.name, f.chain_id)]
        if upid not in pdbe_total_results:
            pdbe_total_results[upid] = FilteredStructure(
                uniprot_accession=upid[0],
                pdb_id=upid[1],
            )
        pdbe_total_results[upid].chain = f
    chain_filtered_files = [f.output_file for f in chain_filtered if f.output_file is not None]
    logger.info("Kept %i files after chain filtering in %s", len(chain_filtered_files), pdb_chain_dir)

    residue_filtered = []
    residue_filtered_files = []
    if do_pdb_residue:
        residue_filtered, residue_filtered_files = _filter_pdb_structures_by_residue_count(
            confidence=confidence,
            chain_filtered_files=chain_filtered_files,
            chain_filtered=chain_filtered,
            output_dir=pdb_residue_dir,
            pdbe_total_results=pdbe_total_results,
            pc2upid=pc2upid,
        )

    if do_ss:
        _filter_pdb_structures_on_secondary_structure(
            final_dir=final_dir,
            secondary_structure=secondary_structure,
            pdbe_total_results=pdbe_total_results,
            pc2upid=pc2upid,
            do_pdb_residue=do_pdb_residue,
            chain_filtered=chain_filtered,
            chain_filtered_files=chain_filtered_files,
            residue_filtered=residue_filtered,
            residue_filtered_files=residue_filtered_files,
        )

    _uncompress_gz_files(pdbe_total_results)

    return pdbe_total_results
