import pytest

from steam_game_switcher.errors import SwitcherError
from steam_game_switcher.steamcmd import get_available_branches, parse_app_info, public_branches

APP_INFO_OUTPUT = r"""
Connecting anonymously to Steam Public...OK
"526870"
{
    "common"
    {
        "name" "Satisfactory"
    }
    "depots"
    {
        "branches"
        {
            "public"
            {
                "buildid" "123"
                "pwdrequired" "0"
            }
            "experimental"
            {
                "buildid" "456"
                "pwdrequired" "0"
            }
            "friends-only"
            {
                "buildid" "789"
                "pwdrequired" "1"
            }
        }
    }
}
Steam Console Client finished.
"""


def test_app_info_parser_extracts_public_branches_and_omits_passworded():
    app_info = parse_app_info(APP_INFO_OUTPUT, 526870)

    assert app_info["common"]["name"] == "Satisfactory"
    assert public_branches(app_info) == ["", "experimental"]


def test_app_info_parser_reports_missing_app_id():
    with pytest.raises(SwitcherError, match="did not contain App ID"):
        parse_app_info('"1"\n{\n}\n', 526870)


def test_branch_cache_is_used_until_expired(monkeypatch):
    game_state = {"branch_cache": {"fetched_at": 1_000, "branches": ["", "experimental"]}}

    def fail_if_refreshed(*_args, **_kwargs):
        raise AssertionError("fresh cache should be used")

    monkeypatch.setattr("steam_game_switcher.steamcmd.fetch_public_branches", fail_if_refreshed)
    branches, warning = get_available_branches(526870, game_state, now=1_001)

    assert branches == ["", "experimental"]
    assert warning is None
