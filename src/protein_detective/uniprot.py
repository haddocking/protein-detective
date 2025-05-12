import logging
from dataclasses import dataclass
from textwrap import dedent

from SPARQLWrapper import JSON, SPARQLWrapper

logger = logging.getLogger(__name__)


@dataclass
class Query:
    taxon_id: str | None
    reviewed: bool | None
    subcellular_location_uniprot: str | None
    subcellular_location_go: str | None
    molecular_function_go: str | None


@dataclass(frozen=True)
class PdbResult:
    id: str
    method: str
    chain: str
    resolution: str | None = None


def _query2dynamic_sparql_triples(query: Query):
    parts: list[str] = []
    if query.taxon_id:
        parts.append(f"?protein up:organism taxon:{query.taxon_id} .")

    if query.reviewed:
        parts.append("?protein up:reviewed true .")
    elif query.reviewed is False:
        parts.append("?protein up:reviewed false .")

    parts.append(_append_subcellular_location_filters(query))

    if query.molecular_function_go:
        if not query.molecular_function_go.startswith("GO:"):
            msg = "Molecular function GO term must start with 'GO:'."
            raise ValueError(msg)
        parts.append(
            dedent(f"""
            ?protein up:classifiedWith|(up:classifiedWith/rdfs:subClassOf) {query.molecular_function_go} .
        """)
        )

    return "\n".join(parts)


def _append_subcellular_location_filters(query: Query) -> str:
    if query.subcellular_location_uniprot:
        subcellular_location_uniprot_part = dedent(f"""
            ?protein up:annotation ?subcellAnnotation .
            ?subcellAnnotation up:locatedIn/up:cellularComponent ?cellcmpt .
            ?cellcmpt skos:prefLabel "{query.subcellular_location_uniprot}" .
        """)
    if query.subcellular_location_go:
        if not query.subcellular_location_go.startswith("GO:"):
            msg = "Subcellular location GO term must start with 'GO:'."
            raise ValueError(msg)
        subcellular_location_go_part = dedent(f"""
            ?protein up:classifiedWith|(up:classifiedWith/rdfs:subClassOf) {query.subcellular_location_go} .
        """)
    if query.subcellular_location_uniprot and query.subcellular_location_go:
        # If both are provided include results for both with logical OR
        return dedent(f"""
            {{
                {subcellular_location_uniprot_part}
            }} UNION {{
                {subcellular_location_go_part}
            }}
        """)
    if query.subcellular_location_uniprot:
        return subcellular_location_uniprot_part
    if query.subcellular_location_go:
        return subcellular_location_go_part
    return ""


def _build_sparql_generic_query(select_clause: str, where_clause: str, limit: int = 10_000) -> str:
    """
    Builds a generic SPARQL query with the given select and where clauses.
    """
    return dedent(f"""
        PREFIX up: <http://purl.uniprot.org/core/>
        PREFIX taxon: <http://purl.uniprot.org/taxonomy/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX GO:<http://purl.obolibrary.org/obo/GO_>

        SELECT {select_clause}
        WHERE {{
            {where_clause}
        }}
        LIMIT {limit}
    """)


def _build_sparql_query_uniprot(query: Query, limit=10_000) -> str:
    dynamic_triples = _query2dynamic_sparql_triples(query)
    # TODO add usefull columns that have 1:1 mapping to protein
    select_clause = "?protein"
    where_clause = dedent(f"""
        # --- Protein Selection ---
        ?protein a up:Protein .
        {dynamic_triples}
    """)
    return _build_sparql_generic_query(select_clause, dedent(where_clause), limit)


def _build_sparql_query_pdb(query: Query, limit=10_000) -> str:
    dynamic_triples = _query2dynamic_sparql_triples(query)
    select_clause = "DISTINCT ?protein ?pdb_db ?pdb_method ?pdb_resolution ?pdb_chain"
    where_clause = dedent(f"""
        # --- Protein Selection ---
        ?protein a up:Protein .
        {dynamic_triples}

        # --- PDB Info ---
        ?protein rdfs:seeAlso ?pdb_db .
        ?pdb_db up:database <http://purl.uniprot.org/database/PDB> .
        ?pdb_db up:method ?pdb_method .
        ?pdb_db up:chainSequenceMapping ?chainSequenceMapping .
        ?chainSequenceMapping up:chain ?pdb_chain .
        OPTIONAL {{ ?pdb_db up:resolution ?pdb_resolution . }}
    """)
    return _build_sparql_generic_query(select_clause, dedent(where_clause), limit)


def _build_sparql_query_af(query: Query, limit=10_000) -> str:
    dynamic_triples = _query2dynamic_sparql_triples(query)
    select_clause = "DISTINCT ?protein ?af_db"
    where_clause = dedent(f"""
        # --- Protein Selection ---
        ?protein a up:Protein .
        {dynamic_triples}

        # --- AlphaFoldDB Info ---
        ?protein rdfs:seeAlso ?af_db .
        ?af_db up:database <http://purl.uniprot.org/database/AlphaFoldDB> .
    """)
    return _build_sparql_generic_query(select_clause, dedent(where_clause), limit)


def _build_sparql_query_emdb(query: Query, limit=10_000) -> str:
    dynamic_triples = _query2dynamic_sparql_triples(query)
    select_clause = "DISTINCT ?protein ?emdb_db"
    where_clause = dedent(f"""
        # --- Protein Selection ---
        ?protein a up:Protein .
        {dynamic_triples}

        # --- EMDB Info ---
        ?protein rdfs:seeAlso ?emdb_db .
        ?emdb_db up:database <http://purl.uniprot.org/database/EMDB> .
    """)
    return _build_sparql_generic_query(select_clause, dedent(where_clause), limit)


def _execute_sparql_search(
    sparql_query: str,
    timeout: int,
) -> list:
    """
    Execute a SPARQL query.
    """
    if timeout > 2_700:
        msg = "Uniprot SPARQL timeout is limited to 2,700 seconds (45 minutes)."
        raise ValueError(msg)

    # Execute the query
    sparql = SPARQLWrapper("https://sparql.uniprot.org/sparql")
    sparql.setReturnFormat(JSON)
    sparql.setTimeout(timeout)

    sparql.setQuery(sparql_query)
    rawresults = sparql.queryAndConvert()
    if not isinstance(rawresults, dict):
        msg = f"Expected rawresults to be a dict, but got {type(rawresults)}"
        raise TypeError(msg)

    bindings = rawresults.get("results", {}).get("bindings")
    if not isinstance(bindings, list):
        logger.warning("SPARQL query did not return 'bindings' list as expected.")
        return []

    logger.debug(bindings)
    return bindings


def _flatten_results_pdb(rawresults: list) -> dict[str, set[PdbResult]]:
    pdb_entries: dict[str, set[PdbResult]] = {}
    for result in rawresults:
        protein = result["protein"]["value"].split("/")[-1]
        if "pdb_db" not in result:  # Should not happen with build_sparql_query_pdb
            continue
        pdb_id = result["pdb_db"]["value"].split("/")[-1]
        method = result["pdb_method"]["value"].split("/")[-1]
        chain = result["pdb_chain"]["value"]
        pdb = PdbResult(id=pdb_id, method=method, chain=chain)
        if "pdb_resolution" in result:
            pdb = PdbResult(
                id=pdb_id,
                method=method,
                chain=chain,
                resolution=result["pdb_resolution"]["value"],
            )
        if protein not in pdb_entries:
            pdb_entries[protein] = set()
        pdb_entries[protein].add(pdb)

    return pdb_entries


def _flatten_results_af(rawresults: list) -> dict[str, set[str]]:
    alphafold_entries: dict[str, set[str]] = {}
    for result in rawresults:
        protein = result["protein"]["value"].split("/")[-1]
        if "af_db" in result:
            af_id = result["af_db"]["value"].split("/")[-1]
            if protein not in alphafold_entries:
                alphafold_entries[protein] = set()
            alphafold_entries[protein].add(af_id)
    return alphafold_entries


def _flatten_results_emdb(rawresults: list) -> dict[str, set[str]]:
    emdb_entries: dict[str, set[str]] = {}
    for result in rawresults:
        protein = result["protein"]["value"].split("/")[-1]
        if "emdb_db" in result:
            emdb_id = result["emdb_db"]["value"].split("/")[-1]
            if protein not in emdb_entries:
                emdb_entries[protein] = set()
            emdb_entries[protein].add(emdb_id)
    return emdb_entries


def search4uniprot(query: Query, limit=10_000, timeout=1_800) -> set[str]:
    """
    Search for UniProtKB entries based on the given query.

    Returns:
        Set of protein IDs.
    """
    sparql_query = _build_sparql_query_uniprot(query, limit)
    logger.info("Executing SPARQL query for UniProt: %s", sparql_query)

    # Type assertion is needed because _execute_sparql_search returns a Union
    raw_results = _execute_sparql_search(
        sparql_query=sparql_query,
        timeout=timeout,
    )
    return {result["protein"]["value"].split("/")[-1] for result in raw_results}


def search4pdb(query: Query, limit=10_000, timeout=1_800) -> dict[str, set[PdbResult]]:
    """
    Search for PDB entries in UniProtKB based on the given query.

    Returns:
        Dictionary with protein IDs as keys and sets of PDB results as values.
    """
    sparql_query = _build_sparql_query_pdb(query, limit)
    logger.info("Executing SPARQL query for PDB: %s", sparql_query)

    # Type assertion is needed because _execute_sparql_search returns a Union
    raw_results = _execute_sparql_search(
        sparql_query=sparql_query,
        timeout=timeout,
    )
    return _flatten_results_pdb(raw_results)


def search4af(query: Query, limit=10_000, timeout=1_800) -> dict[str, set[str]]:
    """
    Search for AlphaFold entries in UniProtKB based on the given query.

    Returns:
        Dictionary with protein IDs as keys and sets of AlphaFold IDs as values.
    """
    sparql_query = _build_sparql_query_af(query, limit)
    logger.info("Executing SPARQL query for AlphaFold: %s", sparql_query)

    # Type assertion is needed because _execute_sparql_search returns a Union
    raw_results = _execute_sparql_search(
        sparql_query=sparql_query,
        timeout=timeout,
    )
    return _flatten_results_af(raw_results)


def search4emdb(query: Query, limit=10_000, timeout=1_800) -> dict[str, set[str]]:
    """
    Search for EMDB entries in UniProtKB based on the given query.

    Returns:
        Dictionary with protein IDs as keys and sets of EMDB IDs as values.
    """
    sparql_query = _build_sparql_query_emdb(query, limit)
    logger.info("Executing SPARQL query for EMDB: %s", sparql_query)

    raw_results = _execute_sparql_search(
        sparql_query=sparql_query,
        timeout=timeout,
    )
    return _flatten_results_emdb(raw_results)
