"""Module dealing with filtering of protein structures.

In protein_quest package the filters are more granular, here we combine them into coarse grained methods.
"""

import logging
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from distributed.deploy.cluster import Cluster
from protein_quest.alphafold.fetch import AlphaFoldEntry
from protein_quest.filters.chain import ChainFilterStatistics, filter_files_on_chain
from protein_quest.filters.combined import CombinedFilterQuery, CombinedFilterResult, combined_filter
from protein_quest.filters.residues import ResidueFilterStatistics
from protein_quest.filters.ss import (
    SecondaryStructureFilterQuery,
    SecondaryStructureFilterResult,
    filter_files_on_secondary_structure,
)
from protein_quest.parallel import SchedulerAddress, map_with_progress
from protein_quest.pdbe.ws import Scores
from protein_quest.structure.formats import read_structure, write_structure
from protein_quest.structure.uniprot import add_uniprot_accessions2structure
from protein_quest.utils import copyfile

if TYPE_CHECKING:
    from protein_detective.db import ProteinPdbRow
else:
    ProteinPdbRow = object  # pragma: no cover

logger = logging.getLogger(__name__)


@dataclass
class FilterOptions:
    """Filter query containing combined and secondary structure filters.

    Parameters:
        secondary_structure: The secondary structure filter query.
        combined: The combined filter query.
    """

    secondary_structure: SecondaryStructureFilterQuery
    combined: CombinedFilterQuery = field(default_factory=CombinedFilterQuery)

    @property
    def combined_query(self) -> CombinedFilterQuery:
        """Get the effective combined filter query."""
        return self.combined


@dataclass
class FilteredStructure:
    """Filter result of a single uniprot+[pdb] entry.

    Parameters:
        uniprot_accession: The UniProt accession.
        pdb_id: The PDB ID if applicable.
        combined: The combined filter result if applicable.
        chain: The chain filter result if applicable.
        residue: Legacy residue filter result used for manually imported structures.
        secondary_structure: A tuple containing:
            - The input file path for the secondary structure filter.
            - The secondary structure filter result.
            - The output file path for the secondary structure filter, if passed.
    """

    uniprot_accession: str
    pdb_id: str | None = None
    combined: CombinedFilterResult | None = None
    chain: ChainFilterStatistics | None = None
    residue: ResidueFilterStatistics | None = None
    secondary_structure: tuple[Path, SecondaryStructureFilterResult, Path | None] | None = None

    @property
    def passed(self) -> bool:
        """Whether the structure passed all filters."""
        if self.secondary_structure is not None and not self.secondary_structure[1].passed:
            return False
        if self.chain is not None and not self.chain.passed:
            return False
        if self.combined is not None:
            return self.combined.passed
        if self.residue is not None:
            return self.residue.passed
        return True

    @property
    def output_file(self) -> Path | None:
        """Get the output file of the last filter that was applied.

        Only valid if the structure passed all filters.
        """
        if not self.passed:
            return None
        if self.secondary_structure is not None and self.secondary_structure[2] is not None:
            return self.secondary_structure[2]
        if self.combined is not None and self.combined.output_file is not None:
            return self.combined.output_file
        if self.residue is not None and self.residue.output_file is not None:
            return self.residue.output_file
        if self.chain is not None and self.chain.output_file is not None:
            return self.chain.output_file
        return None

    @output_file.setter
    def output_file(self, path: Path) -> None:
        """Set the output file of the last filter that was applied.

        Only valid if the structure passed all filters.
        """
        if not self.passed:
            msg = "Cannot set output file for a structure that did not pass all filters."
            raise ValueError(msg)
        if self.secondary_structure is not None:
            input_file, ss_result, _ = self.secondary_structure
            self.secondary_structure = (input_file, ss_result, path)
        elif self.combined is not None:
            self.combined = replace(self.combined, output_file=path)
        elif self.residue is not None:
            self.residue.output_file = path
        elif self.chain is not None:
            self.chain.output_file = path

    def make_relative_to(self, session_dir: Path) -> "FilteredStructure":
        """Make all file paths relative to the given session directory.

        Args:
            session_dir: The session directory to make paths relative to.

        Returns:
            A new FilterResultRow object with paths made relative to the session directory.
        """
        new_row = deepcopy(self)
        if new_row.combined is not None:
            new_row.combined = replace(
                new_row.combined,
                input_file=_make_path_relative(new_row.combined.input_file, session_dir),
                output_file=_make_path_relative(new_row.combined.output_file, session_dir),
            )
        if new_row.chain is not None and new_row.chain.output_file is not None:
            new_row.chain.output_file = _make_path_relative(new_row.chain.output_file, session_dir)
        if new_row.residue is not None and new_row.residue.output_file is not None:
            new_row.residue.output_file = _make_path_relative(new_row.residue.output_file, session_dir)
        if new_row.secondary_structure is not None:
            input_file, ss_result, output_file = new_row.secondary_structure
            new_row.secondary_structure = (
                _make_required_path_relative(input_file, session_dir),
                ss_result,
                _make_path_relative(output_file, session_dir),
            )
        return new_row


def _make_path_relative(path: Path | None, session_dir: Path) -> Path | None:
    if path is None or not path.is_absolute():
        return path
    return path.relative_to(session_dir)


def _make_required_path_relative(path: Path, session_dir: Path) -> Path:
    relative_path = _make_path_relative(path, session_dir)
    if relative_path is None:
        msg = "Path unexpectedly missing while rewriting relative path."
        raise ValueError(msg)
    return relative_path


FilterResults = dict[tuple[str, str | None], FilteredStructure]
"""Type alias for filter results mapping (uniprot_accession, pdb_id?) to FilteredStructure."""


FileNameChain2UniprotPdb = dict[tuple[str, str], tuple[str, str]]
"""Type alias for mapping (pdb_file_name, chain) to (uniprot_accession, pdb_id)."""


def _find_result_key(
    input_file: Path | None,
    alphafold_input_file2upid: Mapping[Path, tuple[str, str | None]],
    pdb_chain_out_file2upid: Mapping[Path, tuple[str, str | None]],
) -> tuple[str, str | None]:
    if input_file is None:
        msg = "Combined filter result is missing an input file."
        raise ValueError(msg)
    if input_file in alphafold_input_file2upid:
        return alphafold_input_file2upid[input_file]
    if input_file in pdb_chain_out_file2upid:
        return pdb_chain_out_file2upid[input_file]
    msg = f"Could not map combined filter input file {input_file} back to a structure"
    raise ValueError(msg)


def _filter_structures_on_secondary_structure(
    secondary_structure: SecondaryStructureFilterQuery,
    final_dir: Path,
    total_results: FilterResults,
) -> None:
    input_file2upid = {r.output_file: upid for upid, r in total_results.items() if r.output_file is not None}
    ss_in_files = list(input_file2upid)
    logger.info("Filtering %i structure files on secondary structure", len(ss_in_files))
    ss_results: list[tuple[Path, SecondaryStructureFilterResult, Path | None]] = []
    for input_file, result in filter_files_on_secondary_structure(file_paths=ss_in_files, query=secondary_structure):
        upid = input_file2upid[input_file]
        output_file: Path | None = None
        if result.passed:
            output_file = final_dir / input_file.name
            copyfile(input_file, output_file, "symlink")
        total_results[upid].secondary_structure = (input_file, result, output_file)
        ss_results.append((input_file, result, output_file))
    nr_kept = len([r for r in ss_results if r[2] is not None])
    logger.info("Kept %i files after secondary structure filtering in %s", nr_kept, final_dir)


def add_uniprot_accessions2structure_wrapper(t: tuple[Path, tuple[str, str | None]]) -> None:
    input_file, (uniprot_acc, pdb_id) = t
    if pdb_id is None:
        return
    s = read_structure(input_file)
    pdb2uniprot = {pdb_id: {("A", uniprot_acc)}}
    ns = add_uniprot_accessions2structure(s, pdb2uniprot)
    if s is not ns:
        write_structure(ns, input_file)


def add_uniprot_accessions2structures(
    pdb_chain_out_file2upid: dict[Path, tuple[str, str | None]],
    scheduler_address: SchedulerAddress,
):
    items = [d for d in pdb_chain_out_file2upid.items() if d[1][1] is not None]
    return map_with_progress(scheduler_address, add_uniprot_accessions2structure_wrapper, items, None)


def filter_structures_with_combined_filter(
    afs: list[AlphaFoldEntry],
    proteinpdbs: list[ProteinPdbRow],
    session_dir: Path,
    options: FilterOptions,
    final_dir: Path,
    scheduler_address: str | Cluster | Literal["sequential"] | None = None,
) -> FilterResults:
    """Filter AlphaFold and PDBe structures with the combined filter.

    PDBe structures are first normalized to the UniProt-mapped chain A before passing them to
    the combined filter. Optional secondary-structure filtering remains a post-processing step.
    """
    secondary_structure = options.secondary_structure
    do_ss = secondary_structure.is_actionable()
    combined_dir = session_dir / "combined_filtered" if do_ss else final_dir
    combined_dir.mkdir(parents=True, exist_ok=True)

    alphafold_input_file2upid = {e.cif_file: (e.uniprot_accession, None) for e in afs if e.cif_file is not None}

    path2chains = {(p.mmcif_file, p.chain) for p in proteinpdbs if p.mmcif_file is not None}
    pc2upid: FileNameChain2UniprotPdb = {
        (p.mmcif_file.name, p.chain): (p.uniprot_acc, p.pdb_id) for p in proteinpdbs if p.mmcif_file is not None
    }
    pdb_chain_dir = session_dir / "pdb_chain_filtered"
    pdb_chain_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Filtering PDBe files on chain of Uniprot to chain A")
    chain_filtered = filter_files_on_chain(
        path2chains, pdb_chain_dir, scheduler_address=scheduler_address, copy_method="symlink"
    )

    total_results: FilterResults = {}
    pdb_chain_out_file2upid: dict[Path, tuple[str, str | None]] = {}
    for chain_result in chain_filtered:
        upid = pc2upid[(chain_result.input_file.name, chain_result.chain_id)]
        total_results[upid] = FilteredStructure(
            uniprot_accession=upid[0],
            pdb_id=upid[1],
            chain=chain_result,
        )
        if chain_result.output_file is not None:
            pdb_chain_out_file2upid[chain_result.output_file] = upid
    logger.info("Kept %i files after chain filtering in %s", len(pdb_chain_out_file2upid), pdb_chain_dir)

    # Some structure files are missing their Uniprot mapping, so we try to add it back
    add_uniprot_accessions2structures(
        pdb_chain_out_file2upid,
        scheduler_address=scheduler_address,
    )

    combined_input_files = [*alphafold_input_file2upid.keys(), *pdb_chain_out_file2upid.keys()]

    scores = {
        proteinpdb.pdb_id.lower(): Scores(
            geometry_quality=proteinpdb.geometry_quality,
            data_quality=None,
            overall_quality=None,
            experiment_data_available=False,
        )
        for proteinpdb in proteinpdbs
        if proteinpdb.geometry_quality is not None
    }

    logger.info("Filtering %i structure files with combined filter", len(combined_input_files))
    combined_results = combined_filter(
        input_files=combined_input_files,
        scores=scores,
        filters=options.combined_query,
        output_dir=combined_dir,
        copy_method="symlink",
        scheduler_address=scheduler_address,
    )

    for combined_result in combined_results:
        upid = _find_result_key(combined_result.input_file, alphafold_input_file2upid, pdb_chain_out_file2upid)
        structure_result = total_results.setdefault(
            upid,
            FilteredStructure(
                uniprot_accession=upid[0],
                pdb_id=upid[1],
            ),
        )
        structure_result.pdb_id = structure_result.pdb_id or combined_result.pdb_id
        structure_result.combined = combined_result

    if do_ss:
        _filter_structures_on_secondary_structure(secondary_structure, final_dir, total_results)

    return total_results
