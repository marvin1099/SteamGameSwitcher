"""Optional Steam client restart and game launch helpers."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

STEAM_SHUTDOWN_TIMEOUT_SECONDS = 20
STEAM_POLL_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True)
class SteamShutdown:
    """Result of gracefully stopping Steam before an appmanifest update."""

    was_running: bool
    launcher: tuple[str, ...] | None = None
    warning: str | None = None

    @property
    def stopped(self) -> bool:
        return self.was_running and self.launcher is not None and self.warning is None


def _steam_command() -> list[str] | None:
    system = platform.system()
    if system == "Linux":
        executable = shutil.which("steam")
        if executable:
            return [executable]
        flatpak = shutil.which("flatpak")
        if flatpak:
            return [flatpak, "run", "com.valvesoftware.Steam"]
        return None

    if system == "Darwin":
        candidates = (
            Path("/Applications/Steam.app/Contents/MacOS/steam_osx"),
            Path.home() / "Applications/Steam.app/Contents/MacOS/steam_osx",
        )
        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate)]
        executable = shutil.which("steam")
        return [executable] if executable else None

    if system == "Windows":
        executable = _windows_steam_executable()
        return [str(executable)] if executable else None

    return None


def _windows_steam_executable() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None

    registry_locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
    )
    for hive, key_name in registry_locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for value_name in ("SteamExe", "SteamPath"):
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    candidate = Path(value)
                    if value_name == "SteamPath":
                        candidate /= "steam.exe"
                    if candidate.is_file():
                        return candidate
        except OSError:
            continue

    executable = shutil.which("steam.exe") or shutil.which("steam")
    return Path(executable) if executable else None


def _steam_is_running() -> tuple[bool, str | None]:
    system = platform.system()
    if system == "Linux":
        proc_root = Path("/proc")
        if proc_root.is_dir():
            for comm_path in proc_root.glob("[0-9]*/comm"):
                try:
                    if comm_path.read_text(encoding="utf-8").strip().casefold() == "steam":
                        return True, None
                except FileNotFoundError:
                    continue
                except OSError as error:
                    return False, f"Could not check whether Steam is running: {error}"
            return False, None
        return _process_name_running(("steam",))

    if system == "Darwin":
        return _process_name_running(("steam_osx", "Steam"))

    if system == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
            return False, f"Could not check whether Steam is running: {error}"
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip()
            if not details:
                details = f"tasklist exited with status {result.returncode}"
            return False, f"Could not check whether Steam is running: {details}"
        return '"steam.exe"' in result.stdout.casefold(), None

    return False, f"Steam restart is not supported on {system}."


def steam_running_status() -> tuple[bool, str | None]:
    """Return whether Steam is running, or why its status could not be checked."""
    return _steam_is_running()


def _process_name_running(names: tuple[str, ...]) -> tuple[bool, str | None]:
    for name in names:
        try:
            result = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
            return False, f"Could not check whether Steam is running: {error}"
        if result.returncode == 0:
            return True, None
        if result.returncode != 1:
            return False, f"Could not check whether Steam is running: {result.stderr.strip()}"
    return False, None


def _start_process(command: list[str]) -> None:
    options: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)


def shutdown_steam_if_running() -> SteamShutdown:
    """Gracefully close Steam before editing a manifest; never force-terminate it."""
    was_running, warning = _steam_is_running()
    if warning or not was_running:
        return SteamShutdown(was_running=was_running, warning=warning)

    command = _steam_command()
    if command is None:
        return SteamShutdown(
            was_running=True,
            warning="Steam is running, but SGS could not find its launcher to restart it.",
        )

    deadline = time.monotonic() + STEAM_SHUTDOWN_TIMEOUT_SECONDS
    try:
        subprocess.run(
            [*command, "-shutdown"],
            capture_output=True,
            text=True,
            timeout=STEAM_SHUTDOWN_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # The shutdown request can outlive the command that sent it. Check the client below.
        pass
    except OSError as error:
        return SteamShutdown(
            was_running=True, warning=f"Could not request a Steam shutdown: {error}"
        )

    while True:
        is_running, warning = _steam_is_running()
        if warning:
            return SteamShutdown(was_running=True, warning=warning)
        if not is_running:
            break
        if time.monotonic() >= deadline:
            return SteamShutdown(
                was_running=True,
                warning="Steam did not close; SGS left it running and did not force-terminate it.",
            )
        time.sleep(STEAM_POLL_INTERVAL_SECONDS)

    return SteamShutdown(was_running=True, launcher=tuple(command))


def relaunch_steam(shutdown: SteamShutdown) -> str | None:
    """Relaunch Steam only if it was running and SGS successfully stopped it."""
    if not shutdown.stopped:
        return None
    try:
        _start_process(list(shutdown.launcher or ()))
    except OSError as error:
        return f"Steam closed, but SGS could not relaunch it: {error}"
    return None


def launch_game(app_id: int) -> str | None:
    """Ask the operating system to open Steam's game-launch URI."""
    uri = f"steam://rungameid/{app_id}"
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(uri)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(
                ["open", uri],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        elif system == "Linux":
            opener = shutil.which("xdg-open")
            if opener is None:
                return "Could not find xdg-open to open the Steam game URI."
            subprocess.Popen(
                [opener, uri],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        else:
            return f"Opening Steam game URIs is not supported on {system}."
    except OSError as error:
        return f"Could not open Steam game URI {uri}: {error}"
    return None
