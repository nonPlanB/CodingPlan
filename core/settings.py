"""Atomic persistence for the user-editable application configuration."""

from pathlib import Path
import os
import tempfile
from typing import Any

import yaml


def save_config(root: Path, config: dict[str, Any]) -> None:
    path = root / "config.yaml"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root,
                                         suffix=".yaml", delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
