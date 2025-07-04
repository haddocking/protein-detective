from pathlib import Path

import dagster as dg
from dagster_duckdb import DuckDBResource

from protein_detective.db import (
    initialize_db,
    load_uniprot_accessions,
    save_alphafolds,
    save_pdbs,
    save_uniprot_accessions,
)
from protein_detective.defs.resources import LimitConfig, PdConfig
from protein_detective.uniprot import search4af, search4pdb, search4uniprot


@dg.asset(
    kinds={"duckdb"},
    key=["proteins", "uniprot_accessions"],
)
def search_uniprot(duckdb: DuckDBResource, config: PdConfig) -> None:
    query = config.uniprot
    limit = config.limit
    uniprot_accessions = search4uniprot(query, limit)
    with duckdb.get_connection() as conn:
        session_dir = Path(".")
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
