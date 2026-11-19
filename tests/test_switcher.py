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
    game_state = {"profiles": {}, "install_dirs": {}}

    plan = build_switch_plan(manifest, game_state, ["", "experimental"], "experimental", False)

    assert plan.old_branch == ""
    assert plan.new_branch == "experimental"
    assert plan.manifest["AppState"]["UserConfig"]["BetaKey"] == "experimental"
    assert plan.manifest["AppState"]["installdir"] == "Example Game"
    assert game_state["profiles"][""] == original
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
    game_state = {"profiles": {}, "install_dirs": {}}

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
    game_state = {"profiles": {}, "install_dirs": {"experimental": "../outside"}}

    with pytest.raises(SwitcherError, match="single folder name"):
        build_switch_plan(manifest, game_state, ["", "experimental"], "experimental", True)
