

from dataclasses import dataclass
import logging
from textwrap import dedent

from SPARQLWrapper import SPARQLWrapper, JSON

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

@dataclass
class Result:
    alphafold: set[str]
    pdb: dict[str, set[PdbResult]]

def query2dynamic_sparql_triples(query: Query):
    parts: list[str] = []
    if query.taxon_id:
        parts.append(f"?protein up:organism taxon:{query.taxon_id} .")

    if query.reviewed:
        parts.append("?protein up:reviewed true .")
    elif query.reviewed is False:
        parts.append("?protein up:reviewed false .")

    if query.subcellular_location_uniprot:
        subcellular_location_uniprot_part = dedent(f"""
            ?protein up:annotation ?subcellAnnotation .
            ?subcellAnnotation up:locatedIn/up:cellularComponent ?cellcmpt .
            ?cellcmpt skos:prefLabel "{query.subcellular_location_uniprot}" .
        """)
    if query.subcellular_location_go:
        if not query.subcellular_location_go.startswith("GO:"):
            raise ValueError("Subcellular location GO term must start with 'GO:'.")
        subcellular_location_go_part = dedent(f"""
            ?protein up:classifiedWith|(up:classifiedWith/rdfs:subClassOf) {query.subcellular_location_go} .
        """)
    if query.subcellular_location_uniprot and query.subcellular_location_go:
        # If both are provided include results for both with logical OR
        parts.append(dedent(f"""
            {{
                {subcellular_location_uniprot_part}
            }} UNION {{
                {subcellular_location_go_part}
            }}
        """))
    elif query.subcellular_location_uniprot:
        parts.append(subcellular_location_uniprot_part)
    elif query.subcellular_location_go:
        parts.append(subcellular_location_go_part)

    if query.molecular_function_go:
        if not query.molecular_function_go.startswith("GO:"):
            raise ValueError("Molecular function GO term must start with 'GO:'.")
        parts.append(dedent(f"""
            ?protein up:classifiedWith|(up:classifiedWith/rdfs:subClassOf) {query.molecular_function_go} .
        """))

    return "\n".join(parts)

def build_sparql_query(query: Query, limit =10_000) -> str:
    dynamic_triples = query2dynamic_sparql_triples(query)

    # TODO allow for return of pdb or alphafold or both
    q = dedent(f"""\
        PREFIX up: <http://purl.uniprot.org/core/>
        PREFIX taxon: <http://purl.uniprot.org/taxonomy/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX GO:<http://purl.obolibrary.org/obo/GO_>

        SELECT DISTINCT ?protein ?pdb_db ?pdb_method ?pdb_resolution ?pdb_chain ?af_db
        WHERE {{
            # --- Protein Selection ---
            ?protein a up:Protein .
                   
            {dynamic_triples}

            # --- Optional PDB Info ---
            OPTIONAL {{
                ?protein rdfs:seeAlso ?pdb_db .
                ?pdb_db up:database <http://purl.uniprot.org/database/PDB> .
                ?pdb_db up:method ?pdb_method .
                ?pdb_db up:chainSequenceMapping ?chainSequenceMapping .
                ?chainSequenceMapping up:chain ?pdb_chain .
                OPTIONAL {{ ?pdb_db up:resolution ?pdb_resolution . }}
            }}

            # --- Optional AlphaFoldDB Info ---
            OPTIONAL {{
                ?protein rdfs:seeAlso ?af_db .
                ?af_db up:database <http://purl.uniprot.org/database/AlphaFoldDB> .
            }}
        }}
        LIMIT {limit}
    """)
    return q

def search(query: Query, limit =10_000, timeout=1_800) -> Result:  
    """
    Search for pdbs and alphafold entries in UniProtKB based on the given query.
    
    Example:

    ```python
    from protein_detective.uniprotkb import search, Query
    query = Query(
        taxon_id="9606",
        reviewed=True,
        subcellular_location_uniprot="nucleus",
        subcellular_location_go="GO:0005634", # Cellular component - Nucleus
        molecular_function_go="GO:0003677" # Molecular function - DNA binding
    )
    results = search(query)
    print(results)
    ```
    
    """
    if timeout > 2_700:
        raise ValueError("Uniprot SPARQL timeout is limited to 2,700 seconds (45 minutes).")    

    q = build_sparql_query(query, limit)

    # Execute the query
    sparql = SPARQLWrapper("https://sparql.uniprot.org/sparql")
    sparql.setReturnFormat(JSON)
    sparql.setTimeout(timeout)

    logger.info("Executing SPARQL query: %s", q)

    sparql.setQuery(q)
    rawresults = sparql.queryAndConvert()
    if not isinstance(rawresults, dict):
        raise TypeError("Expected rawresults to be a dict, but got {}".format(type(rawresults)))

    # Parse the results
    return flatten_results(rawresults["results"]["bindings"])


def flatten_results(rawresults: list[dict]) -> Result:
    alphafold_entries: set[str] = set()
    pdb_entries: dict[str, set[PdbResult]] = {}
    for result in rawresults:
        protein = result["protein"]["value"].split("/")[-1]
        if "af_db" in result:
            af_id = result["af_db"]["value"].split("/")[-1]
            alphafold_entries.add(af_id)
        if "pdb_db" not in result:
            continue
        pdb_id = result["pdb_db"]["value"].split("/")[-1]
        method = result["pdb_method"]["value"].split("/")[-1]
        chain = result["pdb_chain"]["value"]
        pdb = PdbResult(
            id=pdb_id,
            method=method,
            chain=chain
        )
        if 'pdb_resolution' in result:
            pdb = PdbResult(
                id=pdb_id,
                method=method,
                chain=chain,
                resolution = result["pdb_resolution"]["value"],
            )
        if protein not in pdb_entries:
            pdb_entries[protein] = set()
        pdb_entries[protein].add(pdb)

    return Result(
        alphafold=alphafold_entries,
        pdb=pdb_entries,
    )