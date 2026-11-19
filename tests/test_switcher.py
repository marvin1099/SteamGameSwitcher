import copy

import pytest

from steam_game_switcher.errors import SwitcherError
from steam_game_switcher.switcher import build_switch_plan, resolve_branch


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("next", "experimental"),
        ("0", "experimental"),
        ("previous", "preview"),
        ("-", "preview"),
        ("2", "experimental"),
        ("-1", "preview"),
        ("public", ""),
    ],
)
def test_resolve_branch(target, expected):
    assert resolve_branch(["", "experimental", "preview"], "", target) == expected


def test_resolve_branch_rejects_unknown_branch():
    with pytest.raises(SwitcherError, match="Unknown branch"):
        resolve_branch(["", "experimental"], "", "private")


def test_switch_plan_preserves_profile_and_uses_shared_folder():
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "Example Game",
            "installdir": "Example Game",
            "UserConfig": {"BetaKey": ""},
            "MountedConfig": {"BetaKey": ""},
        }
    }
    original = copy.deepcopy(manifest)
    game_state = {"install_dirs": {}}

    plan = build_switch_plan(manifest, game_state, ["", "experimental"], "experimental", False)

    assert plan.old_branch == ""
    assert plan.new_branch == "experimental"
    assert plan.manifest["AppState"]["UserConfig"]["BetaKey"] == "experimental"
    assert plan.manifest["AppState"]["installdir"] == "Example Game"
    assert manifest == original


def test_switch_plan_can_use_a_separate_folder_per_branch():
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "Example Game",
            "installdir": "Example Game",
            "UserConfig": {"BetaKey": ""},
        }
    }
    game_state = {"install_dirs": {}}

    plan = build_switch_plan(manifest, game_state, ["", "experimental"], "experimental", True)

    assert plan.new_install_dir == "Example Game-experimental"
    assert plan.manifest["AppState"]["installdir"] == "Example Game-experimental"


def test_switch_plan_rejects_unsafe_custom_install_directory():
    manifest = {
        "AppState": {
            "name": "Example Game",
            "installdir": "Example Game",
            "UserConfig": {"BetaKey": ""},
        }
    }
    game_state = {"install_dirs": {"experimental": "../outside"}}

    with pytest.raises(SwitcherError, match="single folder name"):
        build_switch_plan(manifest, game_state, ["", "experimental"], "experimental", True)


def test_slug_collisions_produce_distinct_install_directories():
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "Example Game",
            "installdir": "Example Game",
            "UserConfig": {"BetaKey": ""},
        }
    }
    branches = ["", "nightly+linux", "nightly-linux"]
    first_state = {"install_dirs": {}}
    second_state = {"install_dirs": {}}

    first = build_switch_plan(manifest, first_state, branches, "nightly+linux", True)
    second = build_switch_plan(manifest, second_state, branches, "nightly-linux", True)

    assert first.new_install_dir != second.new_install_dir


def test_generated_install_directory_is_portable_and_custom_name_is_validated():
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "Title: Deluxe",
            "installdir": "Title Deluxe",
            "UserConfig": {"BetaKey": ""},
        }
    }
    plan = build_switch_plan(
        manifest,
        {"install_dirs": {}},
        ["", "experimental"],
        "experimental",
        True,
    )
    assert ":" not in plan.new_install_dir

    with pytest.raises(SwitcherError, match="portable"):
        build_switch_plan(
            manifest,
            {"install_dirs": {"experimental": "Title: Deluxe"}},
            ["", "experimental"],
            "experimental",
            True,
        )


def test_generated_unicode_install_directory_is_limited_by_utf8_bytes():
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "遊" * 100,
            "installdir": "CurrentGame",
            "UserConfig": {"BetaKey": ""},
        }
    }

    plan = build_switch_plan(
        manifest,
        {"install_dirs": {}},
        ["", "experimental"],
        "experimental",
        True,
    )

    assert len(plan.new_install_dir.encode("utf-8")) <= 240
    assert len(plan.new_install_dir.rsplit("-", maxsplit=1)[-1]) == 10


def test_custom_install_directory_over_byte_limit_is_rejected():
    manifest = {
        "AppState": {
            "appid": "1234",
            "name": "Game",
            "installdir": "Game",
            "UserConfig": {"BetaKey": ""},
        }
    }

    with pytest.raises(SwitcherError, match="240 UTF-8 bytes"):
        build_switch_plan(
            manifest,
            {"install_dirs": {"experimental": "a" * 241}},
            ["", "experimental"],
            "experimental",
            True,
        )
