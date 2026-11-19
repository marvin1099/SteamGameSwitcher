import json
from pathlib import Path

from steam_game_switcher import cli
from steam_game_switcher.acf import load_acf, save_acf_atomic
from steam_game_switcher.backups import backup_store_path
from steam_game_switcher.errors import SteamCMDNotFoundError


def _manifest():
    return {
        "AppState": {
            "appid": "1234",
            "name": "Example Game",
            "installdir": "Example Game",
            "UserConfig": {"BetaKey": ""},
            "MountedConfig": {"BetaKey": ""},
        }
    }


def test_cli_switch_writes_backup_manifest_and_config(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )

    exit_code = cli.main(
        [
            "--app-id",
            "1234",
            "--manifest",
            str(manifest_path),
            "--config",
            str(config_path),
            "switch",
            "experimental",
        ]
    )

    assert exit_code == 0
    switched_manifest = load_acf(manifest_path)
    assert switched_manifest["AppState"]["UserConfig"]["BetaKey"] == "experimental"
    assert switched_manifest["AppState"]["installdir"] == "Example Game-experimental"
    backup_file = backup_store_path(config_path)
    backup_store = json.loads(backup_file.read_text(encoding="utf-8"))
    assert len(backup_store["entries"]) == 1
    assert backup_store["entries"][0]["data"] == _manifest()
    assert config_path.is_file()
    assert "Manifest updated" in capsys.readouterr().out


def test_cli_dry_run_does_not_change_files(tmp_path, monkeypatch):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    before = manifest_path.read_bytes()
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )

    exit_code = cli.main(
        [
            "--app-id",
            "1234",
            "--manifest",
            str(manifest_path),
            "--config",
            str(config_path),
            "switch",
            "experimental",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert manifest_path.read_bytes() == before
    assert not config_path.exists()
    assert not (tmp_path / "backups.json").exists()


def test_cli_restore_restores_json_backup_and_saves_current_state(tmp_path, monkeypatch):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )
    cli.main(
        [
            "--app-id",
            "1234",
            "--manifest",
            str(manifest_path),
            "--config",
            str(config_path),
            "switch",
            "experimental",
        ]
    )
    backup_store = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    original_backup_id = backup_store["entries"][0]["id"]

    exit_code = cli.main(["--config", str(config_path), "restore", original_backup_id])

    assert exit_code == 0
    assert load_acf(manifest_path) == _manifest()
    updated_store = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    assert len(updated_store["entries"]) == 2

    cli.main(
        [
            "--app-id",
            "1234",
            "--manifest",
            str(manifest_path),
            "--config",
            str(config_path),
            "switch",
            "experimental",
        ]
    )
    cycled_store = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    assert len(cycled_store["entries"]) == 2


def test_cli_migrates_saved_branch_profiles_before_removing_them(tmp_path, monkeypatch):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    public_manifest = _manifest()
    experimental_manifest = _manifest()
    experimental_manifest["AppState"]["installdir"] = "Example Game-experimental"
    experimental_manifest["AppState"]["UserConfig"]["BetaKey"] = "experimental"
    experimental_manifest["AppState"]["MountedConfig"]["BetaKey"] = "experimental"
    save_acf_atomic(manifest_path, public_manifest)
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "games": {
                    "1234": {
                        "branch_cache": {"fetched_at": 0, "branches": []},
                        "install_dirs": {},
                        "separate_install_dirs": False,
                        "profiles": {"": public_manifest, "experimental": experimental_manifest},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )

    exit_code = cli.main(
        [
            "--app-id",
            "1234",
            "--manifest",
            str(manifest_path),
            "--config",
            str(config_path),
            "switch",
            "experimental",
        ]
    )

    assert exit_code == 0
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    saved_game = saved_config["games"]["1234"]
    assert saved_config["schema_version"] == 2
    assert saved_game["separate_install_dirs"] is False
    assert "profiles" not in saved_game
    backups = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    assert len(backups["entries"]) == 2


def test_cli_warns_if_steamcmd_is_missing(tmp_path, monkeypatch, capsys):
    def missing(*_args, **_kwargs):
        raise SteamCMDNotFoundError("Run 'sgs install-steamcmd'.")

    monkeypatch.setattr(cli, "get_available_branches", missing)

    exit_code = cli.main(["--config", str(tmp_path / "config.json"), "branches"])

    assert exit_code == 2
    assert "Warning: Run 'sgs install-steamcmd'." in capsys.readouterr().err


def test_cli_installs_steamcmd_for_user(monkeypatch, capsys):
    executable = Path("/user/data/steam-game-switcher/steamcmd/steamcmd.sh")
    monkeypatch.setattr(cli, "install_steamcmd", lambda: (executable, True))

    exit_code = cli.main(["install-steamcmd"])

    assert exit_code == 0
    assert str(executable) in capsys.readouterr().out
