from pathlib import Path

import pooch
import pytest

# Make asserts in test.helpers render with pytest verbosity
pytest.register_assert_rewrite("tests.helpers")


def _fetch_tutorial_fixture(filename: str, sha256: str) -> Path:
    base_url = "https://github.com/haddocking/powerfit-tutorial/raw/master"
    path = pooch.retrieve(
        url=f"{base_url}/{filename}",
        known_hash=f"sha256:{sha256}",
        fname=filename,
        path=pooch.os_cache("protein-detective-test-fixtures"),
    )
    return Path(path)


@pytest.fixture(scope="session")
def ribosome_map() -> Path:
    return _fetch_tutorial_fixture(
        filename="ribosome-KsgA.map",
        sha256="609fb54903dad68eb02638bdd0ecf175016d585d5b73dbee464fed0e4ed4470d",
    )


@pytest.fixture(scope="session")
def ksga_pdb() -> Path:
    return _fetch_tutorial_fixture(
        filename="KsgA.pdb",
        sha256="6bc1eb01fffc56a855b9d65378810e0fe2da678fadf2a1f1021f9fc8499fd710",
    )


def fetch_cif(filename: str, sha256: str) -> Path:
    base_url = "https://www.ebi.ac.uk/pdbe/entry-files/download/"
    path = pooch.retrieve(
        url=f"{base_url}{filename}",
        known_hash=f"sha256:{sha256}",
        fname=filename,
        path=pooch.os_cache("protein-detective-test-fixtures"),
    )
    return Path(path)


@pytest.fixture
def cif_2y29() -> Path:
    """2y29 x-ray structure with single chain A."""
    return fetch_cif(
        "2y29_updated.cif.gz",
        "c12e4b9ddd2ac4f7034aa964bb7510e4942c60543a43d84bf8d67df04df4b045",
    )
