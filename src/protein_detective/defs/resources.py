import dagster as dg
from dagster_duckdb import DuckDBResource

from protein_detective.uniprot import Query

database_resource = DuckDBResource(database="session.db")


# Can not use @dataclass directly so use multi inheritance
class UniprotConfig(dg.Config, Query): ...

class LimitConfig(dg.Config):
    limit: int = 100

class PdConfig(LimitConfig):
    uniprot: UniprotConfig = UniprotConfig(
        taxon_id="9606",
        reviewed=True,
        subcellular_location_uniprot="nucleus",
        subcellular_location_go=["GO:0005634"],  # Cellular component - Nucleus
        molecular_function_go=["GO:0003677"],  # Molecular function - DNA binding
    )



@dg.definitions
def resources():
    return dg.Definitions(
        resources={
            "duckdb": database_resource,
            "uniprotConfig": PdConfig(),
            "limitConfig": LimitConfig
            # TODO add session_dir?
        }
    )
