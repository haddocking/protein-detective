from pathlib import Path

import dagster as dg
from dagster_duckdb import DuckDBResource

from protein_detective.uniprot import Query

# TODO make db inside session directory
# see https://docs.dagster.io/guides/operate/configuration/run-configuration#defining-configurable-parameters-for-a-resource
database_resource = DuckDBResource(database="session.db")


# Can not use @dataclass directly so use multi inheritance
class UniprotConfig(dg.Config, Query): ...


class LimitConfig(dg.Config):
    limit: int = 100


class SessionDirConfig(dg.Config):
    # Path type not allowed,
    session_dir: str = "."

    @property
    def session_path(self) -> Path:
        return Path(self.session_dir)


class PdConfig(LimitConfig, SessionDirConfig):
    uniprot: UniprotConfig = UniprotConfig(
        taxon_id="9606",
        reviewed=True,
        subcellular_location_uniprot="nucleus",
        subcellular_location_go=["GO:0005634"],  # Cellular component - Nucleus
        molecular_function_go=["GO:0003677"],  # Molecular function - DNA binding
    )


# TODO somehow reuse SingleChainQuery
class PrunePdbsConfig(SessionDirConfig):
    min_residues: int = 100
    max_residues: int = 500


class FilterAfConfig(SessionDirConfig):
    confidence: float = 70.0
    min_threshold: int = 100
    max_threshold: int = 500


@dg.definitions
def resources():
    return dg.Definitions(
        resources={
            "duckdb": database_resource,
            "uniprotConfig": PdConfig(),
            "limitConfig": LimitConfig(),
            "sessionDirConfig": SessionDirConfig(),
            "prunePdbsConfig": PrunePdbsConfig(),
            "filterAfConfig": FilterAfConfig(),
        }
    )
