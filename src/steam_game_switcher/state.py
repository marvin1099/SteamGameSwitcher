"""Persistent per-game settings and branch cache."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

from .errors import SwitcherError

SCHEMA_VERSION = 2


def default_config_path() -> Path:
    """Return the platform-appropriate user configuration file path."""
    return Path(user_config_path("steam-game-switcher", appauthor=False)) / "config.json"


def load_state(path: Path, app_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load global state and the selected game's state, creating defaults."""
    path = path.expanduser()
    if path.exists():
        try:
            root = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SwitcherError(f"Could not load config '{path}': {error}") from error
        if not isinstance(root, dict):
            raise SwitcherError(f"Config '{path}' must contain a JSON object.")
    else:
        root = {}

    schema_version = root.get("schema_version", 1)
    if schema_version == 1:
        # Keep saved branch manifests until the CLI can transfer them to backups.json.
        root["schema_version"] = SCHEMA_VERSION
    elif schema_version != SCHEMA_VERSION:
        raise SwitcherError(
            f"Config '{path}' uses unsupported schema version "
            f"{schema_version!r}; expected {SCHEMA_VERSION}."
        )

    games = root.setdefault("games", {})
    if not isinstance(games, dict):
        raise SwitcherError(f"Config '{path}' has an invalid 'games' section.")

    game = games.setdefault(
        str(app_id),
        {
            "branch_cache": {"fetched_at": 0, "branches": []},
            "install_dirs": {},
            "separate_install_dirs": True,
        },
    )
    if not isinstance(game, dict):
        raise SwitcherError(f"Config entry for App ID {app_id} must be a JSON object.")

    game.setdefault("branch_cache", {"fetched_at": 0, "branches": []})
    game.setdefault("install_dirs", {})
    game.setdefault("separate_install_dirs", True)
    for key in ("branch_cache", "install_dirs"):
        if not isinstance(game[key], dict):
            raise SwitcherError(f"Config entry for App ID {app_id} has an invalid '{key}' section.")
    return root, game


def save_state(path: Path, root: dict[str, Any]) -> None:
    """Atomically save JSON state, retaining the previous file on failure."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(root, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as error:
        raise SwitcherError(f"Could not save config '{path}': {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
