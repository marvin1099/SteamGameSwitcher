import builtins
import json
from pathlib import Path

import pytest

from steam_game_switcher import cli
from steam_game_switcher.acf import load_acf, save_acf_atomic
from steam_game_switcher.backups import add_backup, backup_store_path, save_backup_store
from steam_game_switcher.errors import SteamCMDNotFoundError


@pytest.fixture(autouse=True)
def _assume_steam_is_not_running(monkeypatch):
    monkeypatch.setattr(cli, "steam_running_status", lambda: (False, None))


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


def _seed_numbered_backups(config_path: Path, tmp_path: Path) -> dict[str, str]:
    store = {"schema_version": 1, "entries": []}
    backup_ids = {}
    snapshots = [
        (400, "", "2025-01-01T00:00:00Z"),
        (400, "experimental", "2025-02-01T00:00:00Z"),
        (526870, "", "2025-03-01T00:00:00Z"),
    ]
    for app_id, branch, created_at in snapshots:
        data = {
            "AppState": {
                "appid": str(app_id),
                "installdir": f"Game-{app_id}-{branch or 'public'}",
                "UserConfig": {"BetaKey": branch},
            }
        }
        manifest_path = tmp_path / f"appmanifest_{app_id}.acf"
        backup_id, _ = add_backup(store, app_id, manifest_path, data, branch)
        store["entries"][-1]["created_at"] = created_at
        backup_ids[f"{app_id}:{branch or 'public'}"] = backup_id
    save_backup_store(backup_store_path(config_path), store)
    return backup_ids


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
            "--no-guard",
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


def test_gui_reports_optional_dependency_when_pyside_is_missing(tmp_path, monkeypatch, capsys):
    original_import = builtins.__import__

    def import_without_pyside(name, *args, **kwargs):
        if name.startswith("PySide6"):
            raise ModuleNotFoundError("No module named 'PySide6'", name="PySide6")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_pyside)

    exit_code = cli.main(["--config", str(tmp_path / "config.json"), "gui"])

    assert exit_code == 2
    assert "GUI support requires the optional PySide6 dependency" in capsys.readouterr().err


def test_switch_client_preferences_persist_and_run_after_a_real_switch(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )
    actions = []

    def fake_shutdown():
        actions.append(("shutdown", load_acf(manifest_path)["AppState"]["UserConfig"]["BetaKey"]))
        return cli.SteamShutdown(was_running=True, launcher=("/usr/bin/steam",))

    def fake_relaunch(shutdown):
        actions.append(("relaunch", load_acf(manifest_path)["AppState"]["UserConfig"]["BetaKey"]))
        assert shutdown.stopped
        return None

    monkeypatch.setattr(cli, "shutdown_steam_if_running", fake_shutdown)
    monkeypatch.setattr(cli, "relaunch_steam", fake_relaunch)
    monkeypatch.setattr(cli, "launch_game", lambda app_id: actions.append(("launch", app_id)))

    settings_exit_code = cli.main(
        [
            "--app-id",
            "1234",
            "--config",
            str(config_path),
            "settings",
            "--restart-steam-on-switch",
            "--launch-game-after-switch",
        ]
    )

    assert settings_exit_code == 0
    assert actions == []

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
    assert actions == [
        ("shutdown", ""),
        ("relaunch", "experimental"),
        ("launch", 1234),
    ]
    settings = json.loads(config_path.read_text(encoding="utf-8"))["games"]["1234"]
    assert settings["restart_steam_on_switch"] is True
    assert settings["launch_game_after_switch"] is True
    output = capsys.readouterr().out
    assert "Steam closed before applying branch settings." in output
    assert "Steam restarted." in output
    assert "Opened Steam URI: steam://rungameid/1234" in output


def test_switch_aborts_before_manifest_write_if_steam_will_not_close(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    original_manifest = manifest_path.read_bytes()
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )
    monkeypatch.setattr(
        cli,
        "shutdown_steam_if_running",
        lambda: cli.SteamShutdown(
            was_running=True, warning="Steam did not close; SGS left it running."
        ),
    )

    cli.main(
        [
            "--app-id",
            "1234",
            "--config",
            str(config_path),
            "settings",
            "--restart-steam-on-switch",
        ]
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

    assert exit_code == 2
    assert manifest_path.read_bytes() == original_manifest
    assert "The branch settings were not completed" in capsys.readouterr().err


def test_switch_without_guard_warns_but_edits_manifest_while_steam_runs(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    monkeypatch.setattr(cli, "steam_running_status", lambda: (True, None))
    monkeypatch.setattr(
        cli,
        "shutdown_steam_if_running",
        lambda: (_ for _ in ()).throw(AssertionError("restart was not enabled")),
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
    assert load_acf(manifest_path)["AppState"]["UserConfig"]["BetaKey"] == "experimental"
    assert "Warning: Steam is running" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("steam_status", "message"),
    [
        ((True, None), "Steam is running"),
        ((False, "Steam process status is unavailable."), "Could not verify Steam state"),
    ],
)
def test_switch_guard_refuses_when_steam_is_running_or_unknown(
    tmp_path, monkeypatch, capsys, steam_status, message
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    original_manifest = manifest_path.read_bytes()
    monkeypatch.setattr(cli, "steam_running_status", lambda: steam_status)
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )

    exit_code = cli.main(
        [
            "--guard",
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

    assert exit_code == 2
    assert manifest_path.read_bytes() == original_manifest
    assert message in capsys.readouterr().err


def test_switch_without_guard_warns_and_proceeds_when_steam_state_is_unknown(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    monkeypatch.setattr(
        cli, "steam_running_status", lambda: (False, "Steam process status is unavailable.")
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
    assert load_acf(manifest_path)["AppState"]["UserConfig"]["BetaKey"] == "experimental"
    assert "Could not verify Steam state" in capsys.readouterr().err


def test_noop_switch_saves_preferences_without_restarting_or_launching(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    original_manifest = manifest_path.read_bytes()
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )
    monkeypatch.setattr(
        cli,
        "shutdown_steam_if_running",
        lambda: (_ for _ in ()).throw(AssertionError("a no-op is not a switch")),
    )
    monkeypatch.setattr(
        cli,
        "launch_game",
        lambda _app_id: (_ for _ in ()).throw(AssertionError("a no-op is not a switch")),
    )

    cli.main(
        [
            "--app-id",
            "1234",
            "--config",
            str(config_path),
            "settings",
            "--restart-steam-on-switch",
            "--launch-game-after-switch",
        ]
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
            "public",
        ]
    )

    assert exit_code == 0
    assert manifest_path.read_bytes() == original_manifest
    assert "Already on public" in capsys.readouterr().out
    settings = json.loads(config_path.read_text(encoding="utf-8"))["games"]["1234"]
    assert settings["restart_steam_on_switch"] is True
    assert settings["launch_game_after_switch"] is True
    assert settings["launch_game_when_unchanged"] is False


def test_noop_switch_launches_game_when_enabled(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    launched = []
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )
    cli.main(
        [
            "--app-id",
            "1234",
            "--config",
            str(config_path),
            "settings",
            "--launch-game-when-unchanged",
        ]
    )
    monkeypatch.setattr(cli, "launch_game", launched.append)

    exit_code = cli.main(
        [
            "--app-id",
            "1234",
            "--manifest",
            str(manifest_path),
            "--config",
            str(config_path),
            "switch",
            "public",
        ]
    )

    assert exit_code == 0
    assert launched == [1234]
    assert "Already on public" in capsys.readouterr().out
    settings = json.loads(config_path.read_text(encoding="utf-8"))["games"]["1234"]
    assert settings["launch_game_when_unchanged"] is True


def test_defaults_command_can_enable_launch_for_unchanged_branch(tmp_path, capsys):
    config_path = tmp_path / "config.json"

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "defaults",
            "--launch-game-when-unchanged",
        ]
    )

    assert exit_code == 0
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["games"] == {}
    assert config["default_app_id"] == 526870
    assert config["defaults"]["launch_game_when_unchanged"] is True
    assert "Launch game when branch is unchanged: enabled" in capsys.readouterr().out


def test_settings_command_only_updates_config_without_manifest_or_steam_actions(
    tmp_path, monkeypatch, capsys
):
    config_path = tmp_path / "config.json"

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("settings must not interact with Steam or a manifest")

    monkeypatch.setattr(cli, "steam_running_status", unexpected_call)
    monkeypatch.setattr(cli, "shutdown_steam_if_running", unexpected_call)
    monkeypatch.setattr(cli, "relaunch_steam", unexpected_call)
    monkeypatch.setattr(cli, "launch_game", unexpected_call)

    exit_code = cli.main(
        [
            "--app-id",
            "1234",
            "--config",
            str(config_path),
            "settings",
            "--shared-folder",
            "--restart-steam-on-switch",
            "--launch-game-after-switch",
            "--launch-game-when-unchanged",
        ]
    )

    assert exit_code == 0
    game_settings = json.loads(config_path.read_text(encoding="utf-8"))["games"]["1234"]
    assert game_settings["separate_install_dirs"] is False
    assert game_settings["restart_steam_on_switch"] is True
    assert game_settings["launch_game_after_switch"] is True
    assert game_settings["launch_game_when_unchanged"] is True
    assert "Settings for App ID 1234" in capsys.readouterr().out


def test_public_to_public_metadata_repair_does_not_restart_or_launch(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    manifest = _manifest()
    del manifest["AppState"]["UserConfig"]["BetaKey"]
    del manifest["AppState"]["MountedConfig"]["BetaKey"]
    save_acf_atomic(manifest_path, manifest)
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )
    monkeypatch.setattr(
        cli,
        "shutdown_steam_if_running",
        lambda: (_ for _ in ()).throw(AssertionError("public-to-public is not a switch")),
    )
    monkeypatch.setattr(
        cli,
        "launch_game",
        lambda _app_id: (_ for _ in ()).throw(AssertionError("public-to-public is not a switch")),
    )
    cli.main(
        [
            "--app-id",
            "1234",
            "--config",
            str(config_path),
            "settings",
            "--restart-steam-on-switch",
            "--launch-game-after-switch",
        ]
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
            "public",
        ]
    )

    assert exit_code == 0
    updated = load_acf(manifest_path)
    assert updated["AppState"]["UserConfig"]["BetaKey"] == ""
    output = capsys.readouterr().out
    assert "Update public manifest" in output
    assert "Branch unchanged" in output
    assert "Switch public -> public" not in output


def test_same_branch_switch_completes_external_branch_change_install_dir(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    manifest = _manifest()
    manifest["AppState"]["UserConfig"]["BetaKey"] = "experimental"
    manifest["AppState"]["MountedConfig"]["BetaKey"] = "experimental"
    save_acf_atomic(manifest_path, manifest)
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "games": {
                    "1234": {
                        "branch_cache": {"fetched_at": 0, "branches": []},
                        "install_dirs": {"": "Example Game"},
                        "last_managed_branch": "",
                        "last_managed_install_dir": "Example Game",
                        "separate_install_dirs": True,
                        "restart_steam_on_switch": True,
                        "launch_game_after_switch": False,
                        "launch_game_when_unchanged": False,
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
    monkeypatch.setattr(
        cli,
        "shutdown_steam_if_running",
        lambda: (
            actions.append(("shutdown", load_acf(manifest_path)["AppState"]["installdir"]))
            or cli.SteamShutdown(was_running=True, launcher=("/usr/bin/steam",))
        ),
    )
    actions = []
    monkeypatch.setattr(
        cli,
        "relaunch_steam",
        lambda shutdown: (
            actions.append(("relaunch", load_acf(manifest_path)["AppState"]["installdir"])) or None
        ),
    )
    monkeypatch.setattr(
        cli,
        "steam_running_status",
        lambda: (_ for _ in ()).throw(AssertionError("Steam is shut down before reconciliation")),
    )
    monkeypatch.setattr(
        cli,
        "launch_game",
        lambda _app_id: (_ for _ in ()).throw(AssertionError("launch setting is off")),
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
    updated_manifest = load_acf(manifest_path)
    assert updated_manifest["AppState"]["UserConfig"]["BetaKey"] == "experimental"
    assert updated_manifest["AppState"]["installdir"] == "Example Game-experimental"
    updated_game = json.loads(config_path.read_text(encoding="utf-8"))["games"]["1234"]
    assert updated_game["install_dirs"]["experimental"] == "Example Game-experimental"
    assert updated_game["last_managed_branch"] == "experimental"
    assert updated_game["last_managed_install_dir"] == "Example Game-experimental"
    assert actions == [
        ("shutdown", "Example Game"),
        ("relaunch", "Example Game-experimental"),
    ]
    output = capsys.readouterr().out
    assert "Complete external branch change public -> experimental" in output
    assert "Steam closed before applying branch settings." in output
    assert "Steam restarted." in output


def test_legacy_config_same_branch_request_establishes_baseline_without_steam_actions(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    manifest = _manifest()
    manifest["AppState"]["UserConfig"]["BetaKey"] = "experimental"
    manifest["AppState"]["MountedConfig"]["BetaKey"] = "experimental"
    manifest["AppState"]["installdir"] = "Example Game-experimental"
    save_acf_atomic(manifest_path, manifest)
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "games": {
                    "1234": {
                        "profiles": {},
                        "install_dirs": {"": "Example Game"},
                        "separate_install_dirs": True,
                        "restart_steam_on_switch": True,
                        "launch_game_after_switch": True,
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
    monkeypatch.setattr(
        cli,
        "shutdown_steam_if_running",
        lambda: (_ for _ in ()).throw(AssertionError("same-branch baseline is not a switch")),
    )
    monkeypatch.setattr(
        cli,
        "launch_game",
        lambda _app_id: (_ for _ in ()).throw(AssertionError("same-branch launch is disabled")),
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
    game = json.loads(config_path.read_text(encoding="utf-8"))["games"]["1234"]
    assert game["last_managed_branch"] == "experimental"
    assert game["last_managed_install_dir"] == "Example Game-experimental"
    output = capsys.readouterr().out
    assert "Already on experimental" in output
    assert "Complete external branch change" not in output


def test_defaults_command_sets_preferences_for_new_games_only(tmp_path, capsys):
    config_path = tmp_path / "config.json"

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "defaults",
            "--shared-folder",
            "--restart-steam",
            "--launch-game",
            "--launch-game-when-unchanged",
        ]
    )

    assert exit_code == 0
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["games"] == {}
    assert config["defaults"] == {
        "separate_install_dirs": False,
        "restart_steam_on_switch": True,
        "launch_game_after_switch": True,
        "launch_game_when_unchanged": True,
    }
    assert "Defaults for new games" in capsys.readouterr().out


def test_defaults_can_change_default_app_id_and_commands_can_override_it(
    tmp_path, monkeypatch, capsys
):
    config_path = tmp_path / "config.json"
    exit_code = cli.main(["--config", str(config_path), "defaults", "--app-id", "400"])

    assert exit_code == 0
    assert json.loads(config_path.read_text(encoding="utf-8"))["default_app_id"] == 400
    assert "Default App ID: 400" in capsys.readouterr().out

    app_ids = []
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda app_id, *_args, **_kwargs: (app_ids.append(app_id) or [""], None),
    )

    assert cli.main(["--config", str(config_path), "branches"]) == 0
    assert cli.main(["--config", str(config_path), "--app-id", "1234", "branches"]) == 0
    assert app_ids == [400, 1234]


def test_top_level_help_uses_sgs_and_groups_related_commands():
    help_text = cli._build_parser().format_help()

    assert "usage: sgs" in help_text
    assert "backup" in help_text
    assert "steamcmd" in help_text


def test_switch_install_dir_adds_or_updates_mapping_for_existing_branch(tmp_path, monkeypatch):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental"], None),
    )

    for install_dir in ("FirstExperimental", "UpdatedExperimental"):
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
                "--install-dir",
                install_dir,
            ]
        )

        assert exit_code == 0
        manifest = load_acf(manifest_path)
        assert manifest["AppState"]["installdir"] == install_dir
        saved_config = json.loads(config_path.read_text(encoding="utf-8"))
        game_config = saved_config["games"]["1234"]
        assert game_config["install_dirs"]["experimental"] == install_dir
        assert game_config["separate_install_dirs"] is True


def test_switch_install_dir_rejects_branch_not_in_available_list(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    save_acf_atomic(manifest_path, _manifest())
    original_manifest = manifest_path.read_bytes()
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
            "nightly",
            "--install-dir",
            "NightlyBuild",
        ]
    )

    assert exit_code == 2
    assert "Unknown branch 'nightly'" in capsys.readouterr().err
    assert manifest_path.read_bytes() == original_manifest
    assert not config_path.exists()


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

    exit_code = cli.main(["--config", str(config_path), "backup", "restore", original_backup_id])

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


def test_restore_without_guard_warns_but_proceeds_while_steam_is_running(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    current = _manifest()
    saved = _manifest()
    saved["AppState"]["UserConfig"]["BetaKey"] = "experimental"
    saved["AppState"]["MountedConfig"]["BetaKey"] = "experimental"
    saved["AppState"]["installdir"] = "Example Game-experimental"
    save_acf_atomic(manifest_path, current)
    store = {"schema_version": 1, "entries": []}
    backup_id, _ = add_backup(store, 1234, manifest_path, saved, "experimental")
    save_backup_store(backup_store_path(config_path), store)
    monkeypatch.setattr(cli, "steam_running_status", lambda: (True, None))

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "--manifest",
            str(manifest_path),
            "backup",
            "restore",
            backup_id,
        ]
    )

    assert exit_code == 0
    assert load_acf(manifest_path) == saved
    updated_store = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    assert len(updated_store["entries"]) == 2
    assert "Warning: Steam is running" in capsys.readouterr().err


def test_restore_guard_refuses_to_edit_manifest_while_steam_is_running(
    tmp_path, monkeypatch, capsys
):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    current = _manifest()
    saved = _manifest()
    saved["AppState"]["UserConfig"]["BetaKey"] = "experimental"
    saved["AppState"]["MountedConfig"]["BetaKey"] = "experimental"
    save_acf_atomic(manifest_path, current)
    store = {"schema_version": 1, "entries": []}
    backup_id, _ = add_backup(store, 1234, manifest_path, saved, "experimental")
    save_backup_store(backup_store_path(config_path), store)
    monkeypatch.setattr(cli, "steam_running_status", lambda: (True, None))

    exit_code = cli.main(
        [
            "--guard",
            "--config",
            str(config_path),
            "--manifest",
            str(manifest_path),
            "backup",
            "restore",
            backup_id,
        ]
    )

    assert exit_code == 2
    assert load_acf(manifest_path) == current
    assert "Steam is running" in capsys.readouterr().err


def test_restore_follows_saved_restart_and_launch_preferences(tmp_path, monkeypatch):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    current = _manifest()
    saved = _manifest()
    saved["AppState"]["UserConfig"]["BetaKey"] = "experimental"
    saved["AppState"]["MountedConfig"]["BetaKey"] = "experimental"
    saved["AppState"]["installdir"] = "Example Game-experimental"
    save_acf_atomic(manifest_path, current)
    store = {"schema_version": 1, "entries": []}
    backup_id, _ = add_backup(store, 1234, manifest_path, saved, "experimental")
    save_backup_store(backup_store_path(config_path), store)
    settings_result = cli.main(
        [
            "--app-id",
            "1234",
            "--config",
            str(config_path),
            "settings",
            "--restart-steam-on-switch",
            "--launch-game-after-switch",
        ]
    )
    assert settings_result == 0

    actions = []
    monkeypatch.setattr(
        cli,
        "steam_running_status",
        lambda: (_ for _ in ()).throw(AssertionError("restart preference should shut Steam")),
    )
    monkeypatch.setattr(
        cli,
        "shutdown_steam_if_running",
        lambda: (
            actions.append(("shutdown", load_acf(manifest_path)["AppState"]["installdir"]))
            or cli.SteamShutdown(was_running=True, launcher=("/usr/bin/steam",))
        ),
    )
    monkeypatch.setattr(
        cli,
        "relaunch_steam",
        lambda _shutdown: (
            actions.append(("relaunch", load_acf(manifest_path)["AppState"]["installdir"])) or None
        ),
    )
    monkeypatch.setattr(cli, "launch_game", lambda app_id: actions.append(("launch", app_id)))

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "--manifest",
            str(manifest_path),
            "backup",
            "restore",
            backup_id,
        ]
    )

    assert exit_code == 0
    assert load_acf(manifest_path) == saved
    game = json.loads(config_path.read_text(encoding="utf-8"))["games"]["1234"]
    assert game["last_managed_branch"] == "experimental"
    assert game["last_managed_install_dir"] == "Example Game-experimental"
    assert game["install_dirs"]["experimental"] == "Example Game-experimental"
    assert actions == [
        ("shutdown", "Example Game"),
        ("relaunch", "Example Game-experimental"),
        ("launch", 1234),
    ]


def test_backup_list_reports_malformed_timestamps_without_traceback(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    backup_path = backup_store_path(config_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {"app_id": 526870, "id": "older", "created_at": "2025-01-01T00:00:00Z"},
                    {"app_id": 526870, "id": "malformed", "created_at": None},
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["--config", str(config_path), "backup", "list"])

    assert exit_code == 2
    assert "created_at" in capsys.readouterr().err


def test_backups_and_restore_numbers_are_filtered_by_app_id(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    backup_ids = _seed_numbered_backups(config_path, tmp_path)

    exit_code = cli.main(["--config", str(config_path), "backup", "list", "--app-id", "400"])

    assert exit_code == 0
    output = capsys.readouterr().out.splitlines()
    assert output[0].startswith(f" 1. {backup_ids['400:experimental']}  App 400")
    assert output[1].startswith(f" 2. {backup_ids['400:public']}  App 400")

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "backup",
            "restore",
            "--app-id",
            "400",
            "1",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert (
        f"Restore backup {backup_ids['400:experimental']} for App ID 400" in capsys.readouterr().out
    )


def test_backups_all_and_restore_all_use_global_numbering(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    backup_ids = _seed_numbered_backups(config_path, tmp_path)

    exit_code = cli.main(["--config", str(config_path), "backup", "list", "--all"])

    assert exit_code == 0
    output = capsys.readouterr().out.splitlines()
    assert output[0].startswith(f" 1. {backup_ids['526870:public']}  App 526870")
    assert output[1].startswith(f" 2. {backup_ids['400:experimental']}  App 400")
    assert output[2].startswith(f" 3. {backup_ids['400:public']}  App 400")

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "backup",
            "restore",
            "--global-numbering",
            "2",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert (
        f"Restore backup {backup_ids['400:experimental']} for App ID 400" in capsys.readouterr().out
    )


def test_delete_backup_by_number_removes_entry_and_renumbers_list(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    backup_ids = _seed_numbered_backups(config_path, tmp_path)

    exit_code = cli.main(
        [
            "--config",
            str(config_path),
            "backup",
            "delete",
            "1",
            "--app-id",
            "400",
            "--yes",
        ]
    )

    assert exit_code == 0
    assert (
        f"Deleted backup {backup_ids['400:experimental']} for App ID 400" in capsys.readouterr().out
    )
    store = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    assert [entry["id"] for entry in store["entries"]] == [
        backup_ids["400:public"],
        backup_ids["526870:public"],
    ]

    exit_code = cli.main(["--config", str(config_path), "backup", "list", "--app-id", "400"])

    assert exit_code == 0
    assert capsys.readouterr().out.startswith(f" 1. {backup_ids['400:public']}  App 400")


def test_delete_global_numbering_removes_only_the_selected_backup(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    backup_ids = _seed_numbered_backups(config_path, tmp_path)

    exit_code = cli.main(
        ["--config", str(config_path), "backup", "delete", "--global-numbering", "1", "--yes"]
    )

    assert exit_code == 0
    assert f"Deleted backup {backup_ids['526870:public']}" in capsys.readouterr().out
    store = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    assert {entry["id"] for entry in store["entries"]} == {
        backup_ids["400:public"],
        backup_ids["400:experimental"],
    }


def test_delete_backup_requires_confirmation_by_default(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.json"
    backup_ids = _seed_numbered_backups(config_path, tmp_path)
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "no")

    exit_code = cli.main(
        ["--config", str(config_path), "backup", "delete", backup_ids["400:public"]]
    )

    assert exit_code == 0
    assert "Delete backup" in prompts[0]
    assert "Cancelled; backup was not deleted." in capsys.readouterr().out
    store = json.loads(backup_store_path(config_path).read_text(encoding="utf-8"))
    assert len(store["entries"]) == 3


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
        raise SteamCMDNotFoundError("Run 'sgs steamcmd install'.")

    monkeypatch.setattr(cli, "get_available_branches", missing)

    exit_code = cli.main(["--config", str(tmp_path / "config.json"), "branches"])

    assert exit_code == 2
    assert "Warning: Run 'sgs steamcmd install'." in capsys.readouterr().err


def test_cli_cache_option_is_passed_to_branch_lookup(tmp_path, monkeypatch):
    observed = []

    def fake_get_branches(_app_id, _game_state, _steamcmd, **options):
        observed.append(options)
        return ["", "experimental"], None

    monkeypatch.setattr(cli, "get_available_branches", fake_get_branches)

    exit_code = cli.main(["--config", str(tmp_path / "config.json"), "--cache", "branches"])

    assert exit_code == 0
    assert observed[0]["use_cache"] is True
    assert observed[0]["force_refresh"] is False


def test_cli_installs_steamcmd_for_user(monkeypatch, capsys):
    executable = Path("/user/data/steam-game-switcher/steamcmd/steamcmd.sh")
    observed = []

    def fake_install(*, repair):
        observed.append(repair)
        return executable, True

    monkeypatch.setattr(cli, "install_steamcmd", fake_install)

    for subcommand in ("install", "repair"):
        exit_code = cli.main(["steamcmd", subcommand])
        assert exit_code == 0

    assert observed == [False, True]
    output = capsys.readouterr().out
    assert str(executable) in output
    assert "installed or repaired" in output


def test_cli_generates_shortcuts_for_selected_branch_indices(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "appmanifest_1234.acf"
    config_path = tmp_path / "config.json"
    output_directory = tmp_path / "Desktop"
    sgs_executable = tmp_path / ".local" / "bin" / "sgs"
    save_acf_atomic(manifest_path, _manifest())
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda executable: str(sgs_executable) if executable == "sgs" else None,
    )
    monkeypatch.setattr(
        cli,
        "get_available_branches",
        lambda *_args, **_kwargs: (["", "experimental", "preview"], None),
    )

    exit_code = cli.main(
        [
            "--app-id",
            "1234",
            "--manifest",
            str(manifest_path),
            "--config",
            str(config_path),
            "shortcuts",
            "-1",
            "2",
            "--output",
            str(output_directory),
        ]
    )

    assert exit_code == 0
    for name in ("sgs-1234-preview.desktop", "sgs-1234-experimental.desktop"):
        shortcut = output_directory / name
        assert shortcut.is_file()
        contents = shortcut.read_text(encoding="utf-8")
        assert f'Exec="{sgs_executable}"' in contents
        assert "Terminal=false" in contents
        assert '"-m" "steam_game_switcher"' not in contents
    output = capsys.readouterr().out
    assert f"Shortcut location: {output_directory}" in output
    assert "sgs-1234-preview.desktop" in output
    assert "sgs-1234-experimental.desktop" in output
