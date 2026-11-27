from steam_game_switcher.acf import dump_acf, load_acf, save_acf_atomic


def test_acf_round_trip_preserves_nested_manifest(tmp_path):
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "Example Game",
            "installdir": "Example Game",
            "UserConfig": {"BetaKey": "experimental", "language": "english"},
            "InstalledDepots": {"1235": {"manifest": "987654", "size": "42"}},
        }
    }
    path = tmp_path / "appmanifest_1234.acf"

    save_acf_atomic(path, manifest)

    assert load_acf(path) == manifest
    assert dump_acf(manifest).endswith("\n")
