import subprocess
from pathlib import Path

import pytest

from steam_game_switcher.errors import SwitcherError
from steam_game_switcher.steamcmd import (
    fetch_public_branches,
    get_available_branches,
    parse_app_info,
    public_branches,
)

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


def test_actual_steamcmd_transcript_and_subprocess_call(monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "steamcmd_app_info_526870.txt"
    output = fixture.read_text(encoding="utf-8")
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="SteamCMD log")

    monkeypatch.setattr("steam_game_switcher.steamcmd.find_steamcmd", lambda _exe: "/opt/steamcmd")
    monkeypatch.setattr("steam_game_switcher.steamcmd.subprocess.run", fake_run)

    branches = fetch_public_branches(526870, "steamcmd")

    assert branches == ["", "experimental"]
    assert observed["command"] == ["/opt/steamcmd", "+app_info_print", "526870", "+quit"]
    assert observed["kwargs"]["capture_output"] is True
    assert observed["kwargs"]["text"] is True


def test_branch_cache_is_used_until_expired(monkeypatch):
    game_state = {"branch_cache": {"fetched_at": 1_000, "branches": ["", "experimental"]}}

    def fail_if_refreshed(*_args, **_kwargs):
        raise AssertionError("fresh cache should be used")

    monkeypatch.setattr("steam_game_switcher.steamcmd.fetch_public_branches", fail_if_refreshed)
    branches, warning = get_available_branches(526870, game_state, now=1_001)

    assert branches == ["", "experimental"]
    assert warning is not None
    assert "sgs install-steamcmd" in warning
