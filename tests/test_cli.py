from steam_game_switcher import cli
from steam_game_switcher.acf import load_acf, save_acf_atomic


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
    assert load_acf(manifest_path)["AppState"]["UserConfig"]["BetaKey"] == "experimental"
    assert list(tmp_path.glob("appmanifest_1234.acf.*.bak"))
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
    assert not list(tmp_path.glob("*.bak"))
