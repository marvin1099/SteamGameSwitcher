import os
import sys

import pytest

from steam_game_switcher.errors import SwitcherError
from steam_game_switcher.shortcuts import generate_shortcuts


def _generate(tmp_path, **overrides):
    options = {
        "branches": ["", "experimental", "preview"],
        "selections": ["-1", "2"],
        "current_branch": "",
        "app_id": 1234,
        "game_name": "Example Game",
        "manifest_path": tmp_path / "Steam Library" / "appmanifest_1234.acf",
        "config_path": tmp_path / "config file.json",
        "output_directory": tmp_path / "Desktop",
        "executable": sys.executable,
        "platform_name": "Linux",
    }
    options.update(overrides)
    return generate_shortcuts(**options)


def test_generate_linux_desktop_shortcuts_resolves_negative_and_positive_indices(tmp_path):
    shortcuts = _generate(tmp_path)

    assert [path.name for path in shortcuts] == [
        "sgs-1234-preview.desktop",
        "sgs-1234-experimental.desktop",
    ]
    for path, branch in zip(shortcuts, ("preview", "experimental"), strict=True):
        contents = path.read_text(encoding="utf-8")
        assert f"Name=Switch Example Game to {branch}" in contents
        assert "Terminal=true" in contents
        assert f'"switch" "--" "{branch}"' in contents
        assert os.access(path, os.X_OK)


def test_generate_windows_vbs_shortcut_runs_without_a_console_window(tmp_path):
    shortcuts = _generate(tmp_path, platform_name="Windows", selections=["preview"])

    assert len(shortcuts) == 1
    assert shortcuts[0].suffix == ".vbs"
    contents = shortcuts[0].read_text(encoding="utf-16")
    assert 'CreateObject("WScript.Shell")' in contents
    assert "shell.Run " in contents
    assert ", 0, False" in contents
    assert "steam_game_switcher" in contents


def test_generate_macos_command_shortcut_is_executable(tmp_path):
    shortcuts = _generate(tmp_path, platform_name="Darwin", selections=["public"])

    assert shortcuts[0].suffix == ".command"
    assert shortcuts[0].read_text(encoding="utf-8").startswith("#!/bin/sh\nexec ")
    assert os.access(shortcuts[0], os.X_OK)


def test_branch_names_with_matching_filename_slugs_get_distinct_files(tmp_path):
    shortcuts = _generate(
        tmp_path,
        branches=["", "nightly+linux", "nightly-linux"],
        selections=["nightly+linux", "nightly-linux"],
    )

    assert len(shortcuts) == 2
    assert shortcuts[0].name != shortcuts[1].name
    assert all(path.is_file() for path in shortcuts)


def test_generate_shortcuts_does_not_overwrite_without_force(tmp_path):
    shortcuts = _generate(tmp_path, selections=["experimental"])
    original_contents = shortcuts[0].read_text(encoding="utf-8")

    with pytest.raises(SwitcherError, match="Pass --force"):
        _generate(tmp_path, selections=["experimental"])

    _generate(tmp_path, selections=["experimental"], force=True)
    assert shortcuts[0].read_text(encoding="utf-8") == original_contents
