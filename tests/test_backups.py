import json

import pytest

from steam_game_switcher.backups import (
    add_backup,
    backup_store_path,
    find_backup,
    load_backup_store,
    save_backup_store,
)
from steam_game_switcher.errors import SwitcherError


def test_backup_store_deduplicates_identical_manifest_data(tmp_path):
    config_path = tmp_path / "config.json"
    backup_path = backup_store_path(config_path)
    manifest_path = tmp_path / "appmanifest_1234.acf"
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "Example Game",
            "installdir": "Example Game",
            "UserConfig": {"BetaKey": ""},
        }
    }
    store = load_backup_store(backup_path)

    first_id, first_created = add_backup(store, 1234, manifest_path, manifest, "")
    second_id, second_created = add_backup(store, 1234, manifest_path, manifest, "")
    save_backup_store(backup_path, store)
    reloaded = load_backup_store(backup_path)

    assert backup_path == tmp_path / "backups.json"
    assert first_id == second_id
    assert first_created is True
    assert second_created is False
    assert len(reloaded["entries"]) == 1
    assert find_backup(reloaded, first_id)["data"] == manifest


def test_backup_integrity_check_detects_modified_destination(tmp_path):
    store = load_backup_store(tmp_path / "backups.json")
    manifest = {"AppState": {"appid": "1234", "installdir": "Game"}}
    backup_id, _ = add_backup(store, 1234, tmp_path / "appmanifest_1234.acf", manifest, "")
    store["entries"][0]["manifest_path"] = str(tmp_path / "other.acf")

    with pytest.raises(SwitcherError, match="metadata failed its integrity check"):
        find_backup(store, backup_id)


def test_backup_store_rejects_invalid_created_at_timestamp(tmp_path):
    backup_path = tmp_path / "backups.json"
    backup_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {"created_at": "2025-01-01T00:00:00Z"},
                    {"created_at": None},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SwitcherError, match="created_at"):
        load_backup_store(backup_path)
