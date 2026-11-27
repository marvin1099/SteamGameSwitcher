import subprocess
from pathlib import Path

import pytest

from steam_game_switcher.errors import SteamCMDError, SwitcherError
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
    monkeypatch.setattr("steam_game_switcher.steamcmd.find_steamcmd", lambda _exe: None)
    branches, warning = get_available_branches(526870, game_state, now=1_001)

    assert branches == ["", "experimental"]
    assert warning is not None
    assert "sgs steamcmd install" in warning


def test_cache_option_uses_expired_cache_without_refreshing(monkeypatch):
    cached_branches = ["", "experimental"]
    game_state = {"branch_cache": {"fetched_at": 1_000, "branches": cached_branches}}

    def fail_if_refreshed(*_args, **_kwargs):
        raise AssertionError("--cache must not refresh expired cache data")

    monkeypatch.setattr("steam_game_switcher.steamcmd.fetch_public_branches", fail_if_refreshed)

    branches, warning = get_available_branches(
        526870,
        game_state,
        use_cache=True,
        now=1_000 + 25 * 60 * 60,
    )

    assert branches == cached_branches
    assert warning == "Using cached branch data as requested; it may be stale."
    assert game_state["branch_cache"]["fetched_at"] == 1_000


def test_cache_option_fetches_when_no_branch_cache_exists(monkeypatch):
    game_state = {"branch_cache": {"fetched_at": 1_000, "branches": []}}
    fetched_branches = ["", "experimental"]
    observed = []

    def fake_fetch(app_id, executable):
        observed.append((app_id, executable))
        return fetched_branches

    monkeypatch.setattr("steam_game_switcher.steamcmd.fetch_public_branches", fake_fetch)

    branches, warning = get_available_branches(
        526870,
        game_state,
        executable="steamcmd",
        use_cache=True,
        now=2_000,
    )

    assert observed == [(526870, "steamcmd")]
    assert branches == fetched_branches
    assert warning is None
    assert game_state["branch_cache"] == {"fetched_at": 2_000, "branches": fetched_branches}


def test_explicit_refresh_does_not_fall_back_to_stale_cache(monkeypatch):
    game_state = {"branch_cache": {"fetched_at": 1_000, "branches": ["", "removed"]}}

    def fail_refresh(*_args, **_kwargs):
        raise SteamCMDError("network unavailable")

    monkeypatch.setattr("steam_game_switcher.steamcmd.fetch_public_branches", fail_refresh)

    with pytest.raises(SteamCMDError, match="network unavailable"):
        get_available_branches(526870, game_state, force_refresh=True, now=100_000)

    assert game_state["branch_cache"]["branches"] == ["", "removed"]
