import os

from steam_game_switcher.paths import DEFAULT_NAME_MAX, install_dir_component_limit


def test_install_dir_component_limit_queries_common_filesystem(tmp_path, monkeypatch):
    steamapps = tmp_path / "steamapps"
    common = steamapps / "common"
    common.mkdir(parents=True)
    manifest_path = steamapps / "appmanifest_1234.acf"
    manifest_path.touch()
    observed = {}

    def fake_pathconf(path, name):
        observed["path"] = path
        observed["name"] = name
        return 192

    monkeypatch.setattr(os, "pathconf", fake_pathconf, raising=False)

    assert install_dir_component_limit(manifest_path) == 192
    assert observed == {"path": common, "name": "PC_NAME_MAX"}


def test_install_dir_component_limit_falls_back_when_pathconf_fails(tmp_path, monkeypatch):
    manifest_path = tmp_path / "appmanifest_1234.acf"

    def unsupported_pathconf(_path, _name):
        raise OSError("unsupported filesystem query")

    monkeypatch.setattr(os, "pathconf", unsupported_pathconf, raising=False)

    assert install_dir_component_limit(manifest_path) == DEFAULT_NAME_MAX
