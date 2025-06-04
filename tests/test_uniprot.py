from textwrap import dedent

from protein_detective.uniprot import Query, _build_sparql_query_pdb, _build_sparql_query_uniprot


def assertQueryEqual(actual, expected):
    """
    Helper function to assert that two SPARQL queries are equal.
    Strips leading whitespace for comparison.
    """
    actual_lines = [line.lstrip() for line in actual.split("\n")]
    expected_lines = [line.strip() for line in expected.split("\n")]
    assert actual_lines == expected_lines, f"Expected:\n{expected}\n\nActual:\n{actual}"


def test_build_sparql_query_uniprot():
    # Test with a simple query
    query = Query(
        taxon_id="9606",
        reviewed=True,
        subcellular_location_uniprot="nucleus",
        subcellular_location_go="GO:0005634",  # Cellular component - Nucleus
        molecular_function_go="GO:0003677",  # Molecular function - DNA binding
    )
    result = _build_sparql_query_uniprot(query, limit=10)

    expected = dedent("""
        PREFIX up: <http://purl.uniprot.org/core/>
        PREFIX taxon: <http://purl.uniprot.org/taxonomy/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX GO:<http://purl.obolibrary.org/obo/GO_>

        SELECT ?protein
        WHERE {

            # --- Protein Selection ---
            ?protein a up:Protein .
            ?protein up:organism taxon:9606 .
            ?protein up:reviewed true .

            {

            ?protein up:annotation ?subcellAnnotation .
            ?subcellAnnotation up:locatedIn/up:cellularComponent ?cellcmpt .
            ?cellcmpt skos:prefLabel "nucleus" .

            } UNION {

            ?protein up:classifiedWith|(up:classifiedWith/rdfs:subClassOf) GO:0005634 .

            }


            ?protein up:classifiedWith|(up:classifiedWith/rdfs:subClassOf) GO:0003677 .


            }

        LIMIT 10
    """)

    assertQueryEqual(result, expected)


def test_build_sparql_query_pdb():
    result = _build_sparql_query_pdb(["O15178", "O15294"], limit=42)
    expected = dedent("""
        PREFIX up: <http://purl.uniprot.org/core/>
        PREFIX taxon: <http://purl.uniprot.org/taxonomy/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX GO:<http://purl.obolibrary.org/obo/GO_>

        SELECT ?protein ?pdb_db ?pdb_method ?pdb_resolution
        (GROUP_CONCAT(DISTINCT ?pdb_chain; separator=",") AS ?pdb_chains)

        WHERE {

            # --- Protein Selection ---
            VALUES (?ac) { ("O15178") ("O15294")}
            BIND (IRI(CONCAT("http://purl.uniprot.org/uniprot/",?ac)) AS ?protein)
            ?protein a up:Protein .


            # --- PDB Info ---
            ?protein rdfs:seeAlso ?pdb_db .
            ?pdb_db up:database <http://purl.uniprot.org/database/PDB> .
            ?pdb_db up:method ?pdb_method .
            ?pdb_db up:chainSequenceMapping ?chainSequenceMapping .
            BIND(STRAFTER(STR(?chainSequenceMapping), "isoforms/") AS ?isoformPart)
            FILTER(STRSTARTS(?isoformPart, CONCAT(?ac, "-")))
            ?chainSequenceMapping up:chain ?pdb_chain .
            OPTIONAL { ?pdb_db up:resolution ?pdb_resolution . }


        }
        GROUP BY ?protein ?pdb_db ?pdb_method ?pdb_resolution
        LIMIT 42
    """)
    assertQueryEqual(result, expected)
