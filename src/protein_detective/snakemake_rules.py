from pathlib import Path

import duckdb

from protein_detective.alphafold.density import filter_on_density
from protein_detective.db import (
    ProteinPdbRow,
    connect,
    load_alphafold_ids,
    load_pdb_ids,
    load_pdbs,
    save_alphafolds,
    save_alphafolds_files,
    save_pdbs,
    save_query,
    save_uniprot_accessions,
)
from protein_detective.pdbe.io import SingleChainQuery, write_single_chain_pdb_files
from protein_detective.uniprot import Query, search4af, search4pdb, search4uniprot
from protein_detective.workflow import DensityFilterQuery, af_fetch, pdbe_fetch


def search_rule(query: Query, limit: int, out_file):
    uniprot_accessions = search4uniprot(query, limit)
    pdbs = search4pdb(uniprot_accessions, limit=limit)
    af_result = search4af(uniprot_accessions, limit=limit)

    session_dir = Path(out_file).parent
    with connect(session_dir, database=out_file, read_only=True) as con:
        save_query(query, con)
        save_uniprot_accessions(uniprot_accessions, con)
        save_pdbs(pdbs, con)
        save_alphafolds(af_result, con)


def retrieve_pdbe_rule(search_db, download_dir):
    session_dir = Path(search_db).parent
    with connect(session_dir, database=search_db, read_only=True) as con:
        pdb_ids = load_pdb_ids(con)
        pdbe_fetch(pdb_ids, Path(download_dir))


def retrieve_af_rule(search_db, download_dir, summaries_db):
    session_dir = Path(search_db).parent
    with connect(session_dir, database=search_db, read_only=True) as con:
        af_ids = load_alphafold_ids(con)
        afs = af_fetch(af_ids, Path(download_dir))
    with connect(session_dir, database=summaries_db) as con:
        save_alphafolds_files(afs, con)


def filter_pdbe_rule(in_dir: str, search_db: str, query: SingleChainQuery, out_dir: str):
    session_dir = Path(search_db).parent
    with connect(session_dir, database=search_db, read_only=True) as con:
        raw_proteinpdbs = load_pdbs(con)
        # search_db does not know which files where retrieved, so we need to find them
        input_files = {p.stem.upper(): p for p in Path(in_dir).glob("*.cif")}
        proteinpdbs = []
        for pdb in raw_proteinpdbs:
            if pdb.id in input_files:
                row = ProteinPdbRow(
                    id=pdb.id,
                    uniprot_chains=pdb.uniprot_chains,
                    uniprot_acc=pdb.uniprot_acc,
                    mmcif_file=input_files[pdb.id],
                )
                proteinpdbs.append(row)

    result_generator = write_single_chain_pdb_files(
        proteinpdbs,
        session_dir,
        single_chain_dir=Path(out_dir),
        query=query,
    )
    # Loop through the generator to execute the writing of files
    list(result_generator)


def filter_af_rule(in_dir: str, query: DensityFilterQuery, out_dir: str):
    af_files = Path(in_dir).glob("*.pdb")
    result_generator = filter_on_density(
        af_files,
        query,
        Path(out_dir),
    )
    list(result_generator)


def powerfit_report_rule(root_result_dir: str, output_file: str):
    query = """
        SELECT
            parse_dirpath(filename) AS result_dir,
            filename AS solutions_file,
            rank, cc, fishz, relz,
            [x,y,z]::FLOAT[3] AS translation,
            [a11, a12, a13, a21, a22, a23, a31, a32, a33]::FLOAT[9] AS rotation,
        FROM
          read_csv(
            ? || '/**/solutions.out',
            filename=True, normalize_names=True
          )
        ORDER BY cc DESC
    """
    duckdb.sql(query, params=(root_result_dir,)).df().to_csv(output_file)
