from pathlib import Path
from textwrap import dedent
from typing import Any, Literal

from molviewspec import MVSJ, GlobalMetadata, States, create_builder, molstar_html, molstar_notebook, molstar_streamlit
from molviewspec.builder import Representation, Root, Snapshot, VolumeRepresentation
from pandas import DataFrame

Renderer = Literal["html", "notebook", "streamlit"]
"""Which molstar renderer to use for visualization."""


def _render_state(state, data, renderer: Renderer, ui: Literal["viewer", "stories"] = "viewer"):
    if renderer == "notebook":
        return molstar_notebook(state=state, data=data, ui=ui, width=1500, height=900)
    if renderer == "html":
        return molstar_html(state=state, data=data, ui=ui)
    if renderer == "streamlit":
        return molstar_streamlit(state=state, data=data, ui=ui)

    msg = f"Renderer '{renderer}' is not implemented. Supported: 'notebook'."
    raise NotImplementedError(msg)


def _add_model_to_builder(builder: Root, model: Path) -> Representation:
    return (
        builder.download(url=model.name)
        .parse(format="pdb")
        .model_structure()
        .component()
        .representation()
        .color(color="blue")
    )


def _add_density_to_builder(builder: Root, density: Path) -> VolumeRepresentation:
    return (
        builder.download(url=density.name)
        .parse(format="map")
        .volume()
        .representation(type="isosurface", relative_isovalue=3, show_wireframe=True)
        .color(color="green")
        .opacity(opacity=0.1)
    )


def _create_snapshot_description(fitted_model: dict[str, Any]) -> str:
    source = ""
    if fitted_model["pdb_id"] is not None:
        source = dedent(f"""\
            - Source: PDBe
            - PDB ID: [{fitted_model["pdb_id"]}](https://www.ebi.ac.uk/pdbe/entry/pdb/{fitted_model["pdb_id"]})
        """)
    elif fitted_model["af_id"] is not None:
        source = dedent(f"""\
            - Source: AlphaFold
            - AlphfoldDB ID: {fitted_model["af_id"]}
        """)
    else:
        msg = "Fitted model must have either a PDB ID or an AlphaFold ID."
        raise ValueError(msg)
    translation = fitted_model["translation"].round(3)
    rotation = fitted_model["rotation"].round(3)
    return (
        dedent(f"""
            - Run: {fitted_model["powerfit_run_id"]}
            - Structure: {fitted_model["structure"]}
            - Rank: {fitted_model["rank"]} (within run of structure)
            - Cross correlation score: {fitted_model["cc"]:.2f}
            - Fish-z score: {fitted_model["fishz"]:.2f}
            - Rel-z score: {fitted_model["relz"]:.2f}
            - Translation: {translation}
            - Rotation: {rotation}
        """)
        + source
        + dedent(
            f"""- Uniprot accesion: [{fitted_model["uniprot_acc"]}](https://www.uniprot.org/uniprot/{fitted_model["uniprot_acc"]})"""
        )
    )


def create_snapshot(fitted_model: dict[str, Any], density: Path) -> tuple[Snapshot, Path]:
    builder = create_builder()
    _add_density_to_builder(builder, density)
    fitted_model_file = Path(fitted_model["fitted_model_file"])
    _add_model_to_builder(builder, fitted_model_file)
    description = _create_snapshot_description(fitted_model)
    return (
        builder.get_snapshot(
            key=f"{fitted_model['powerfit_run_id']}-{fitted_model['structure']}-{fitted_model['rank']}",
            title=f"{fitted_model['structure']} - {fitted_model['rank']} ({fitted_model['powerfit_run_id']})",
            description=description,
            description_format="markdown",
        ),
        fitted_model_file,
    )


def show_fitted_models_and_density(fitted_models: DataFrame, density: Path, renderer: Renderer = "notebook"):
    """Visualizes fitted models and their associated density map with molstar.

    Args:
        fitted_models: The fitted models retrieved with [load_fitted_models][protein_detective.db.load_fitted_models].
        density: Path to the density map file (e.g., CCP4 format).
        renderer: Renderer to use for visualization.
    """
    snapshots = []
    data = {}
    data[density.name] = density.read_bytes()
    for _, row in fitted_models.iterrows():
        snapshot, fitted_model_file = create_snapshot(row.to_dict(), density)
        snapshots.append(snapshot)
        data[fitted_model_file.name] = fitted_model_file.read_bytes()

    state = MVSJ(data=States(snapshots=snapshots, metadata=GlobalMetadata(description="Fitted models and density map")))

    _render_state(state, data, renderer, "stories")


def show_structure_and_density(structure: Path | str, density: Path, renderer: Renderer = "notebook"):
    """Visualizes a structure and its associated density map with molstar.

    Args:
        structure: Path to the structure file (PDB format).
        density: Path to the density map file (e.g., CCP4 format).
        renderer: Renderer to use for visualization.
    """
    structure = Path(structure)
    builder = create_builder()
    _add_density_to_builder(builder, density)
    _add_model_to_builder(builder, structure)

    # TODO use camera or focus to point camera to structure

    state = builder.get_state(indent=2)
    data = {}
    data[density.name] = density.read_bytes()
    data[structure.name] = structure.read_bytes()
    _render_state(state, data, renderer)
