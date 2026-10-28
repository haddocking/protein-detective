"""Ship precompiled dashboard assets without requiring Node.js at installation."""

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface  # pyrefly: ignore [missing-import]


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        assets = Path(self.root) / "dashboard" / "dist"
        if not (assets / "index.html").is_file():
            if version == "editable":
                return
            msg = "Dashboard assets are missing. Run `cd dashboard && npm ci && npx vp build` before packaging."
            raise RuntimeError(msg)
        destination = "protein_detective/dashboard/static" if self.target_name == "wheel" else "dashboard/dist"
        build_data.setdefault("force_include", {})[str(assets)] = destination
