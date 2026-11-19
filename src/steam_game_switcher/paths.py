"""Steam library and appmanifest discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import vdf

from .errors import SwitcherError

DEFAULT_NAME_MAX = 255


def install_dir_component_limit(manifest_path: Path) -> int:
    """Return the destination filesystem's single-component name limit."""
    common_directory = manifest_path.parent / "common"
    probe_path = common_directory if common_directory.is_dir() else manifest_path.parent
    try:
        limit = os.pathconf(probe_path, "PC_NAME_MAX")
    except (AttributeError, OSError, ValueError):
        return DEFAULT_NAME_MAX
    return limit if limit > 0 else DEFAULT_NAME_MAX


def _steam_roots() -> list[Path]:
    home = Path.home()
    roots = [
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        home / "Library" / "Application Support" / "Steam",
    ]
    program_files = os.environ.get("PROGRAMFILES(X86)") or os.environ.get("PROGRAMFILES")
    if program_files:
        roots.append(Path(program_files) / "Steam")

    unique: dict[str, Path] = {}
    for root in roots:
        unique.setdefault(os.path.normcase(str(root.resolve(strict=False))), root)
    return list(unique.values())


def _library_steamapps(steam_root: Path) -> list[Path]:
    libraries = [steam_root / "steamapps"]
    library_file = steam_root / "steamapps" / "libraryfolders.vdf"
    if not library_file.is_file():
        return libraries

    try:
        parsed: dict[str, Any] = vdf.loads(library_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return libraries

    entries = parsed.get("libraryfolders", {})
    if not isinstance(entries, dict):
        return libraries
    for entry in entries.values():
        library_path = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(library_path, str) and library_path:
            libraries.append(Path(library_path).expanduser() / "steamapps")
    return libraries


def find_manifest(
    app_id: int,
    steamapps: Path | None = None,
    manifest: Path | None = None,
) -> Path:
    """Resolve an installed app manifest from explicit paths or Steam libraries."""
    expected_name = f"appmanifest_{app_id}.acf"
    if manifest is not None:
        path = manifest.expanduser()
        if not path.is_file():
            raise SwitcherError(f"Manifest file does not exist: {path}")
        return path.resolve()

    if steamapps is not None:
        path = steamapps.expanduser() / expected_name
        if not path.is_file():
            raise SwitcherError(f"App manifest not found: {path}")
        return path.resolve()

    local = Path.cwd() / expected_name
    if local.is_file():
        return local.resolve()

    searched: set[str] = set()
    for root in _steam_roots():
        for library in _library_steamapps(root):
            normalized = os.path.normcase(str(library.resolve(strict=False)))
            if normalized in searched:
                continue
            searched.add(normalized)
            candidate = library / expected_name
            if candidate.is_file():
                return candidate.resolve()

    raise SwitcherError(
        f"Could not find {expected_name} in the usual Steam libraries. "
        "Pass --steamapps or --manifest to select it explicitly."
    )
