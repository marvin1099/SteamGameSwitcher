"""Deduplicated JSON backups of Steam appmanifest data and restore helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import SwitcherError

BACKUP_SCHEMA_VERSION = 1


def backup_store_path(config_path: Path) -> Path:
    """Return ``backups.json`` beside the selected configuration file."""
    return config_path.expanduser().resolve().parent / "backups.json"


def load_backup_store(path: Path) -> dict[str, Any]:
    """Load the JSON backup index, creating an empty in-memory store if absent."""
    path = path.expanduser()
    if not path.exists():
        return {"schema_version": BACKUP_SCHEMA_VERSION, "entries": []}

    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SwitcherError(f"Could not load backup file '{path}': {error}") from error

    if not isinstance(store, dict) or store.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise SwitcherError(f"Backup file '{path}' has an unsupported format.")
    if not isinstance(store.get("entries"), list) or not all(
        isinstance(entry, dict) for entry in store["entries"]
    ):
        raise SwitcherError(f"Backup file '{path}' has an invalid 'entries' list.")
    return store


def _canonical_json(data: dict[str, Any]) -> str:
    try:
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise SwitcherError(f"Manifest data cannot be stored as JSON: {error}") from error


def add_backup(
    store: dict[str, Any],
    app_id: int,
    manifest_path: Path,
    data: dict[str, Any],
    branch: str,
) -> tuple[str, bool]:
    """Add a backup unless the same app, path, and manifest data already exist."""
    resolved_path = str(manifest_path.expanduser().resolve())
    canonical_data = _canonical_json(data)
    content_hash = hashlib.sha256(canonical_data.encode("utf-8")).hexdigest()
    identity = f"{app_id}\0{resolved_path}\0{content_hash}"
    backup_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]

    for entry in store["entries"]:
        if entry.get("id") == backup_id:
            return backup_id, False

    store["entries"].append(
        {
            "id": backup_id,
            "app_id": app_id,
            "manifest_path": resolved_path,
            "branch": branch,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "sha256": content_hash,
            "data": copy.deepcopy(data),
        }
    )
    return backup_id, True


def save_backup_store(path: Path, store: dict[str, Any]) -> None:
    """Atomically write the JSON backup index."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(store, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as error:
        raise SwitcherError(f"Could not save backup file '{path}': {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def find_backup(store: dict[str, Any], backup_id: str) -> dict[str, Any]:
    """Return a verified backup entry by its short ID."""
    for entry in store["entries"]:
        if entry.get("id") != backup_id:
            continue
        data = entry.get("data")
        app_id = entry.get("app_id")
        path = entry.get("manifest_path")
        if not isinstance(data, dict) or not isinstance(app_id, int) or not isinstance(path, str):
            raise SwitcherError(f"Backup '{backup_id}' is malformed.")
        expected_hash = hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()
        if entry.get("sha256") != expected_hash:
            raise SwitcherError(f"Backup '{backup_id}' failed its integrity check.")
        app_state = data.get("AppState")
        if not isinstance(app_state, dict) or str(app_state.get("appid", app_id)) != str(app_id):
            raise SwitcherError(f"Backup '{backup_id}' does not contain the expected App ID.")
        return entry
    raise SwitcherError(f"Backup '{backup_id}' was not found.")
