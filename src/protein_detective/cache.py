"""Functions that deal with reusing data from another session."""

import dataclasses
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from platformdirs import user_cache_dir

from protein_detective.alphafold import AlphaFoldEntry, DownloadableFormat
from protein_detective.db import (
    connect,
    copy_search_results,
    load_alphafolds,
    load_pdbs,
    load_uniprot_queries,
    save_alphafolds_files,
    save_pdb_files,
)
from protein_detective.uniprot import Query

if TYPE_CHECKING:
    from protein_detective.workflow import WhatRetrieve

logger = logging.getLogger(__name__)


cache_dir = Path(user_cache_dir("protein-detective", ensure_exists=True))
cache_uniprot_root = cache_dir / "uniprot"
cache_uniprot_root.mkdir(parents=True, exist_ok=True)


def _generate_query_hash(query: Query, limit: int) -> str:
    """Generates a hash for the given query and limit.

    Returns:
        A SHA-256 hash of the query and limit, which can be used to identify the query uniquely.
    """
    query_dict = asdict(query)
    query_dict["limit"] = limit
    body = json.dumps(query_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def try_reusing_search_results_from_another_session(query: Query, session_dir: Path, limit: int):
    """Tries to reuse search results from a previous session if the same query has been run before.

    To detect if the same query has been run before, it generates a hash of the query and checks if a symlink
    with that hash exists in the cache directory.
    On unix systems the cache directory is ~/.cache/protein-detective/.
    If it does, the results are copied from the cached session directory.
    If it does not, a new symlink is created pointing to the current session directory.

    Args:
        query: The search query.
        session_dir: The path to the current session directory.
        limit: The limit on the number of search results.
    """
    qhash = _generate_query_hash(query, limit)
    cache_path = cache_uniprot_root / qhash
    if cache_path.exists() and cache_path.readlink().exists():
        cached_session_dir = cache_path.readlink()
        if session_dir.absolute() == cached_session_dir.absolute():
            logger.warning("Running same query in this session dir again.")
        else:
            with connect(session_dir) as con:
                rel_cached_session_dir = cached_session_dir.relative_to(session_dir.absolute(), walk_up=True)
                logger.warning(f"Query seen before, copying search results from {rel_cached_session_dir} session.")
                copy_search_results(cached_session_dir, con)
    else:
        cache_path.unlink(missing_ok=True)
        cache_path.symlink_to(session_dir.absolute())


def try_linking_files_from_another_session(
    session_dir: Path, what: set["WhatRetrieve"], what_af_formats: set[DownloadableFormat], download_dir: Path
) -> tuple[dict[str, Path], list[AlphaFoldEntry]]:
    """Tries to link files from another session if the same query has been run before.

    Cache logic is explained in [try_reusing_search_results_from_another_session][].

    Args:
        session_dir: The path to the current session directory.
        what: A set of file types to link.
        what_af_formats: A set of AlphaFold formats to link.
        download_dir: The directory where files are downloaded to normally.

    Returns:
        A tuple containing:
        - A dictionary mapping file IDs to their linked paths for PDBe files.
        - A list of AlphaFoldEntry objects with linked paths for AlphaFold files.

    Raises:
        ValueError: If no UniProt queries results are found in the session database.
    """
    # Check if there is an another session with same query and downloaded files
    with connect(session_dir, read_only=True) as con:
        uniprot_queries = load_uniprot_queries(con)
    if not uniprot_queries:
        msg = "No UniProt queries results found in the session database. Please run a search first."
        raise ValueError(msg)
    query, limit = uniprot_queries[0]
    if len(uniprot_queries) > 1:
        logger.warning(
            "More than one UniProt query found in the session database. "
            "Only using the first one to see if it was retrieved in another session"
        )

    qhash = _generate_query_hash(query, limit)
    cached_session_dir = cache_uniprot_root / qhash
    linked_files = {}
    current_afs = []
    if (
        not cached_session_dir.exists()
        or not cached_session_dir.readlink().exists()
        or cached_session_dir.resolve() == session_dir.absolute()
    ):
        logger.info("No cached session found for query, downloading files instead of linking to existing files.")
        return linked_files, current_afs
    cached_session_dir = cached_session_dir.readlink().relative_to(session_dir.absolute(), walk_up=True)
    logger.info(
        'Found cached session "%s" with same query, linking files instead of re-downloading', cached_session_dir
    )
    if "pdbe" in what:
        linked_files = _symlink_cached_pdbe_files(session_dir, download_dir, cached_session_dir)
    if "alphafold" in what:
        current_afs = _symlink_cached_alphafold_files(session_dir, what_af_formats, download_dir, cached_session_dir)
    return linked_files, current_afs


def _camel_to_snake_case(name: str) -> str:
    """Convert a camelCase string to snake_case."""
    return "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip("_")


def _symlink_cached_alphafold_files(
    session_dir: Path, what_af_formats: set[DownloadableFormat], download_dir: Path, cached_session_dir: Path
) -> list[AlphaFoldEntry]:
    with connect(cached_session_dir, read_only=True) as cache_con:
        cached_afs = load_alphafolds(cache_con)
    if cached_afs:
        rel_cached_session_dir = cached_session_dir.absolute().relative_to(session_dir.absolute(), walk_up=True)
        logger.warning(
            'AlphaFold files already downloaded in session "%s". Symlinking instead of downloading.',
            rel_cached_session_dir,
        )
    current_afs: list[AlphaFoldEntry] = []
    for af in cached_afs:
        af_files = {}
        for af_format in what_af_formats:
            # DownloadableFormat uses camelcAse, while AlphaFoldEntry uses snake_case, so convert
            entry_key = _camel_to_snake_case(af_format) + "_file"
            cached_file = getattr(af, entry_key)
            if cached_file is None:
                continue
            linked_file = download_dir / cached_file.name
            if not linked_file.exists():
                rel_cached_file = cached_file.resolve().relative_to(download_dir.absolute(), walk_up=True)
                linked_file.symlink_to(rel_cached_file)
                af_files[entry_key] = linked_file.relative_to(session_dir)
        current_af = dataclasses.replace(af, **af_files)
        current_afs.append(current_af)
    with connect(session_dir) as scon:
        save_alphafolds_files(current_afs, scon)
    return current_afs


def _symlink_cached_pdbe_files(session_dir: Path, download_dir: Path, cached_session_dir: Path) -> dict[str, Path]:
    with connect(cached_session_dir, read_only=True) as cache_con:
        cached_pdbes = load_pdbs(cache_con)
    if cached_pdbes:
        logger.warning(
            'PDBe files already downloaded in session "%s". Symlinking instead of downloading.', cached_session_dir
        )
    linked_files: dict[str, Path] = {}
    for pdb in cached_pdbes:
        if pdb.mmcif_file:
            current_pdb = download_dir / pdb.mmcif_file.name
            if current_pdb.exists():
                continue
            rel_cached_file = pdb.mmcif_file.resolve().relative_to(download_dir.absolute(), walk_up=True)
            current_pdb.symlink_to(rel_cached_file)
            linked_files[pdb.id] = current_pdb.relative_to(session_dir)
    with connect(session_dir) as scon:
        save_pdb_files(linked_files, scon)
    return linked_files
