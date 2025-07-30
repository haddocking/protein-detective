"""Functions that deal with reusing data from another session."""

import dataclasses
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path

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
    uniprot_search_counts,
)
from protein_detective.uniprot import Query

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


def try_reusing_search_results_from_another_session(
    query: Query, session_dir: Path, limit: int
) -> tuple[int, int, int, int] | None:
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

    Returns:
        If the search results were reused, returns a tuple containing the counts.
        If the search results were not reused, returns None.
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
                return uniprot_search_counts(con)
    else:
        cache_path.unlink(missing_ok=True)
        cache_path.symlink_to(session_dir.absolute())
    return None


def find_session_with_same_query(session_dir: Path) -> Path | None:
    """Finds a session directory with the same Uniprot query as the given session.

    Args:
        session_dir: The session directory.

    Returns:
        The path to the cached session directory if found, otherwise None.

    Raises:
        ValueError: If no UniProt queries results are found in the session database of session_dir.
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
    if (
        not cached_session_dir.exists()
        or not cached_session_dir.readlink().exists()
        or cached_session_dir.resolve() == session_dir.absolute()
    ):
        logger.info("Unable to find session with same query, downloading files instead of linking to existing files.")
        return None
    cached_session_dir = cached_session_dir.readlink().relative_to(session_dir.absolute(), walk_up=True)
    logger.info(
        'Found cached session "%s" with same query, linking files instead of re-downloading', cached_session_dir
    )
    return cached_session_dir


def symlink_cached_alphafold_files(
    session_dir: Path, what_af_formats: set[DownloadableFormat], download_dir: Path, cached_session_dir: Path
) -> int:
    """Symlink cached AlphaFold files from another session to the current session directory.

    Args:
        session_dir: The current session directory.
        what_af_formats: The set of AlphaFold formats to symlink.
        download_dir: The directory where the files are downloaded.
        cached_session_dir: The directory of the cached session from which to symlink files.

    Returns:
        The number of AlphaFold entries processed.
    """
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
            entry_key = af.format2attr(af_format)
            cached_file = af.by_format(af_format)
            if cached_file is None or not cached_file.exists():
                msg = (
                    f"{af_format} file for AlphaFold entry {af.uniprot_acc} does not exist in {cached_session_dir}. "
                    f"Please run `protein-detective retrieve --what-af-formats {af_format} {cached_session_dir}`"
                    " command first."
                )
                raise FileNotFoundError(msg)
            linked_file = download_dir / cached_file.name
            if not linked_file.exists():
                rel_cached_file = cached_file.resolve().relative_to(download_dir.absolute(), walk_up=True)
                linked_file.symlink_to(rel_cached_file)
                af_files[entry_key] = linked_file.relative_to(session_dir)
        current_af = dataclasses.replace(af, **af_files)
        current_afs.append(current_af)
    with connect(session_dir) as scon:
        save_alphafolds_files(current_afs, scon)
    return len(current_afs)


def symlink_cached_pdbe_files(session_dir: Path, download_dir: Path, cached_session_dir: Path) -> int:
    """Symlink cached PDBe files from another session to the current session directory.

    Args:
        session_dir: The current session directory.
        download_dir: The directory where the files are downloaded.
        cached_session_dir: The directory of the cached session from which to symlink files.

    Returns:
        The number of PDBe files processed.
    """
    with connect(cached_session_dir, read_only=True) as cache_con:
        cached_pdbes = load_pdbs(cache_con)
    if cached_pdbes:
        logger.warning(
            'PDBe files already downloaded in session "%s". Symlinking instead of downloading.', cached_session_dir
        )
    linked_files: dict[str, Path] = {}
    for pdb in cached_pdbes:
        if pdb.mmcif_file:
            if not pdb.mmcif_file.exists():
                msg = (
                    f"{pdb.mmcif_file} does not exist in {cached_session_dir}. "
                    f"Please run `protein-detective retrieve {cached_session_dir}` command first."
                )
                raise FileNotFoundError(msg)
            current_pdb = download_dir / pdb.mmcif_file.name
            if current_pdb.exists():
                logger.info(
                    f"Output file {current_pdb} already exists. Skipping symlinking for {pdb.mmcif_file}.",
                )
                continue
            rel_cached_file = pdb.mmcif_file.resolve().relative_to(download_dir.absolute(), walk_up=True)
            current_pdb.symlink_to(rel_cached_file)
            linked_files[pdb.id] = current_pdb.relative_to(session_dir)
        else:
            msg = (
                f"File for PDB entry {pdb.id} does not exist in {cached_session_dir}. "
                f"Please run `protein-detective retrieve {cached_session_dir}` command first."
            )
            raise FileNotFoundError(msg)
    with connect(session_dir) as scon:
        save_pdb_files(linked_files, scon)
    return len(linked_files)
