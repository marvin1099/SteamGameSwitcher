import subprocess

from steam_game_switcher import steam_client


def test_shutdown_steam_skips_when_client_is_not_running(monkeypatch):
    monkeypatch.setattr(steam_client, "_steam_is_running", lambda: (False, None))
    monkeypatch.setattr(
        steam_client,
        "_steam_command",
        lambda: (_ for _ in ()).throw(AssertionError("should not locate Steam")),
    )

    result = steam_client.shutdown_steam_if_running()
    assert result.was_running is False
    assert result.warning is None


def test_shutdown_steam_requests_graceful_shutdown_before_manifest_edit(monkeypatch):
    running_states = iter(((True, None), (False, None)))
    observed_shutdown = []
    monkeypatch.setattr(steam_client, "_steam_is_running", lambda: next(running_states))
    monkeypatch.setattr(steam_client, "_steam_command", lambda: ["/usr/bin/steam"])
    monkeypatch.setattr(
        steam_client.subprocess,
        "run",
        lambda command, **_kwargs: (
            observed_shutdown.append(command) or subprocess.CompletedProcess(command, 0)
        ),
    )
    result = steam_client.shutdown_steam_if_running()

    assert result.was_running is True
    assert result.stopped is True
    assert result.launcher == ("/usr/bin/steam",)
    assert observed_shutdown == [["/usr/bin/steam", "-shutdown"]]


def test_shutdown_steam_does_not_force_close_client_after_timeout(monkeypatch):
    monkeypatch.setattr(steam_client, "_steam_is_running", lambda: (True, None))
    monkeypatch.setattr(steam_client, "_steam_command", lambda: ["/usr/bin/steam"])
    monkeypatch.setattr(steam_client.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(steam_client.time, "monotonic", iter((0, 21)).__next__)
    result = steam_client.shutdown_steam_if_running()

    assert result.was_running is True
    assert result.warning is not None
    assert "did not close" in result.warning


def test_relaunch_steam_starts_only_a_successfully_stopped_client(monkeypatch):
    observed_launch = []
    monkeypatch.setattr(steam_client, "_start_process", observed_launch.append)
    stopped = steam_client.SteamShutdown(was_running=True, launcher=("/usr/bin/steam",))

    assert steam_client.relaunch_steam(stopped) is None
    assert steam_client.relaunch_steam(steam_client.SteamShutdown(was_running=False)) is None
    assert observed_launch == [["/usr/bin/steam"]]


def test_launch_game_opens_steam_uri_with_system_handler(monkeypatch):
    opened = []
    monkeypatch.setattr(steam_client.platform, "system", lambda: "Linux")
    monkeypatch.setattr(steam_client.shutil, "which", lambda _name: "/usr/bin/xdg-open")
    monkeypatch.setattr(
        steam_client.subprocess, "Popen", lambda command, **_kwargs: opened.append(command)
    )

    assert steam_client.launch_game(526870) is None
    assert opened == [["/usr/bin/xdg-open", "steam://rungameid/526870"]]
