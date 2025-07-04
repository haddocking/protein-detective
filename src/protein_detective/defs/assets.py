from pathlib import Path

import dagster as dg
from dagster_duckdb import DuckDBResource

from protein_detective.alphafold.density import DensityFilterQuery
from protein_detective.db import (
    initialize_db,
    load_alphafold_ids,
    load_alphafolds,
    load_pdb_ids,
    load_pdbs,
    load_uniprot_accessions,
    save_alphafolds,
    save_alphafolds_files,
    save_density_filtered,
    save_pdb_files,
    save_pdbs,
    save_single_chain_pdb_files,
    save_uniprot_accessions,
)
from protein_detective.defs.resources import FilterAfConfig, LimitConfig, PdConfig, PrunePdbsConfig, SessionDirConfig
from protein_detective.pdbe.fetch import fetch as pdbe_fetch
from protein_detective.pdbe.io import SingleChainQuery, write_single_chain_pdb_files
from protein_detective.uniprot import search4af, search4pdb, search4uniprot
from protein_detective.workflow import af_fetch, af_relative_to, filter_on_density


@dg.asset(
    kinds={"duckdb"},
    key=["uniprot_accessions"],
)
def search_uniprot(duckdb: DuckDBResource, config: PdConfig) -> None:
    query = config.uniprot
    limit = config.limit
    session_dir = config.session_path
    uniprot_accessions = search4uniprot(query, limit)
    with duckdb.get_connection() as conn:
        initialize_db(session_dir, conn)
        save_uniprot_accessions(uniprot_accessions, conn)


@dg.asset(
    kinds={"duckdb"},
    key=["pdbe_ids"],
    deps=[search_uniprot],
)
def pdbs_of_uniprot(duckdb: DuckDBResource, config: LimitConfig) -> None:
    with duckdb.get_connection() as conn:
        uniprot_accessions = load_uniprot_accessions(conn)
        limit = config.limit
        uniprot2pdbs = search4pdb(uniprot_accessions, limit=limit)
        save_pdbs(uniprot2pdbs, conn)


@dg.asset(
    kinds={"duckdb"},
    key=["alphafold_ids"],
    deps=[search_uniprot],
)
def alphafolds_of_uniprot(duckdb: DuckDBResource, config: LimitConfig) -> None:
    with duckdb.get_connection() as conn:
        uniprot_accessions = load_uniprot_accessions(conn)
        limit = config.limit
        af_ids = search4af(uniprot_accessions, limit=limit)
        save_alphafolds(af_ids, conn)


@dg.asset(
    kinds={"fs", "duckdb"},
    key=["pdbe_files"],
    deps=[pdbs_of_uniprot],
)
def download_pdbs(duckdb: DuckDBResource, config: SessionDirConfig) -> Path:
    with duckdb.get_connection() as conn:
        pdb_ids = load_pdb_ids(conn)

        session_dir = config.session_path
        save_dir = session_dir / "pdbe_files"
        save_dir.mkdir(parents=True, exist_ok=True)

        files = pdbe_fetch(pdb_ids, save_dir)
        save_pdb_files(files, conn)
        return save_dir


@dg.asset(
    kinds={"fs", "duckdb"},
    key=["pruned_pdbs"],
    deps=[download_pdbs],
)
def prune_pdbs(duckdb: DuckDBResource, config: PrunePdbsConfig) -> Path:
    session_dir = config.session_path
    query = SingleChainQuery(**config.model_dump(exclude={"session_dir"}))
    single_chain_dir = session_dir / "filtered_pdbs"
    single_chain_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.get_connection() as conn:
        proteinpdbs = load_pdbs(conn)

        results = list(write_single_chain_pdb_files(proteinpdbs, session_dir, single_chain_dir, query))

        save_single_chain_pdb_files(results, query, conn)
        return single_chain_dir


@dg.asset(
    kinds={"fs", "duckdb"},
    key=["af_files"],
    deps=[alphafolds_of_uniprot],
)
def download_afs(duckdb: DuckDBResource, config: SessionDirConfig) -> Path:
    with duckdb.get_connection() as conn:
        af_ids = load_alphafold_ids(conn)

        session_dir = config.session_path
        save_dir = session_dir / "alphafold_files"
        save_dir.mkdir(parents=True, exist_ok=True)

        afs = af_fetch(af_ids, save_dir)

        sr_afs = [af_relative_to(af, session_dir) for af in afs]
        save_alphafolds_files(sr_afs, conn)
        return save_dir


@dg.asset(
    kinds={"duckdb", "fs"},
    key=["alphafolds"],
    deps=[download_afs],
)
def filter_afs(duckdb: DuckDBResource, config: FilterAfConfig) -> Path:
    session_dir = config.session_path
    query = DensityFilterQuery(**config.model_dump(exclude={"session_dir"}))
    density_filtered_dir = session_dir / "filtered_afs"
    density_filtered_dir.mkdir(parents=True, exist_ok=True)

    with duckdb.get_connection() as conn:
        afs = load_alphafolds(conn)
        alphafold_pdb_files = [e.pdb_file for e in afs if e.pdb_file is not None]
        uniproc_accs = [e.uniprot_acc for e in afs]

        density_filtered = list(filter_on_density(alphafold_pdb_files, query, density_filtered_dir))

        save_density_filtered(
            query,
            density_filtered,
            uniproc_accs,
            conn,
        )
        return density_filtered_dir
