from pathlib import Path
from typing import Literal

from molviewspec import create_builder, molstar_html, molstar_notebook, molstar_streamlit


def show_structure_and_density(
    structure: Path | str, density: Path, renderer: Literal["html", "notebook", "streamlit"] = "notebook"
):
    structure = Path(structure)
    builder = create_builder()
    builder.download(url=structure.name).parse(format="pdb").model_structure().component().representation().color(
        color="blue"
    )
    builder.download(url=density.name).parse(format="map").volume().representation(
        type="isosurface", relative_isovalue=3, show_wireframe=True
    ).color(color="green").opacity(opacity=0.1)

    # TODO use camera or focus to point camera to structure

    state = builder.get_state(indent=2)
    data = {}
    data[structure.name] = structure.read_bytes()
    data[density.name] = density.read_bytes()

    if renderer == "notebook":
        return molstar_notebook(state=state, data=data)
    if renderer == "html":
        return molstar_html(state=state, data=data)
    if renderer == "streamlit":
        return molstar_streamlit(state=state, data=data)

    msg = f"Renderer '{renderer}' is not implemented. Supported: 'notebook'."
    raise NotImplementedError(msg)
