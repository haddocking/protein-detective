from textwrap import dedent

from protein_detective.uniprot import Query, build_sparql_query


def test_build_sparql_query():
    # Test with a simple query
    query = Query(
        taxon_id="9606",
        reviewed=True,
        subcellular_location_uniprot="nucleus",
        subcellular_location_go="GO:0005634",  # Cellular component - Nucleus
        molecular_function_go="GO:0003677",  # Molecular function - DNA binding
    )
    result = build_sparql_query(query, limit=10)

    expected = dedent("""\
        PREFIX up: <http://purl.uniprot.org/core/>
        PREFIX taxon: <http://purl.uniprot.org/taxonomy/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX GO:<http://purl.obolibrary.org/obo/GO_>

        SELECT DISTINCT ?protein ?pdb_db ?pdb_method ?pdb_resolution ?pdb_chain ?af_db
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


            # --- Optional PDB Info ---
            OPTIONAL {
                ?protein rdfs:seeAlso ?pdb_db .
                ?pdb_db up:database <http://purl.uniprot.org/database/PDB> .
                ?pdb_db up:method ?pdb_method .
                ?pdb_db up:chainSequenceMapping ?chainSequenceMapping .
                ?chainSequenceMapping up:chain ?pdb_chain .
                OPTIONAL { ?pdb_db up:resolution ?pdb_resolution . }
            }

            # --- Optional AlphaFoldDB Info ---
            OPTIONAL {
                ?protein rdfs:seeAlso ?af_db .
                ?af_db up:database <http://purl.uniprot.org/database/AlphaFoldDB> .
            }
        }
        LIMIT 10
    """)

    # Compare without leading whitespaces
    assert [r.lstrip() for r in result.split("\n")] == [
        e.strip() for e in expected.split("\n")
    ]
