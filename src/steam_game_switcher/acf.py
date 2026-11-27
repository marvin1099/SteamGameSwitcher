"""Read and safely write Steam's Valve Data Format manifest files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import vdf

from .errors import SwitcherError


def load_acf(path: Path) -> dict[str, Any]:
    """Load an ACF/VDF file, preserving its nested key/value structure."""
    try:
        data = vdf.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise SwitcherError(f"Could not read manifest '{path}': {error}") from error
    except Exception as error:
        raise SwitcherError(f"Could not parse manifest '{path}': {error}") from error

    if not isinstance(data, dict):
        raise SwitcherError(f"Manifest '{path}' does not contain a VDF object.")
    return data


def dump_acf(data: dict[str, Any]) -> str:
    """Serialize a VDF object in Steam-compatible, readable form."""
    return vdf.dumps(data, pretty=True) + "\n"


def save_acf_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write a manifest through a temporary file to avoid partial updates."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = path.stat().st_mode if path.exists() else None
    temporary_path: Path | None = None

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(dump_acf(data))
            stream.flush()
            os.fsync(stream.fileno())

        if original_mode is not None:
            temporary_path.chmod(original_mode)
        os.replace(temporary_path, path)

        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            # Directory handles are not fsync-able on every supported platform.
            pass
        else:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    except OSError as error:
        raise SwitcherError(f"Could not safely write manifest '{path}': {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
