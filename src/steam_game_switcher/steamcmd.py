"""SteamCMD integration for discovering publicly available game branches."""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any

import vdf

from .errors import SteamCMDError, SteamCMDNotFoundError
from .steamcmd_install import find_steamcmd

CACHE_TTL_SECONDS = 24 * 60 * 60


def _extract_app_block(output: str, app_id: int) -> str:
    """Extract an app's outer VDF block from SteamCMD's noisy console output."""
    app_key = re.search(rf'(?m)^\s*"{re.escape(str(app_id))}"\s*$', output)
    if app_key is None:
        raise SteamCMDError(f"SteamCMD output did not contain App ID {app_id}.")

    opening = output.find("{", app_key.end())
    if opening < 0:
        raise SteamCMDError(f"SteamCMD returned an incomplete block for App ID {app_id}.")

    depth = 0
    in_string = False
    escaped = False
    for position in range(opening, len(output)):
        character = output[position]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return output[app_key.start() : position + 1]

    raise SteamCMDError(f"SteamCMD returned an unterminated block for App ID {app_id}.")


def parse_app_info(output: str, app_id: int) -> dict[str, Any]:
    """Parse an app-info VDF object from SteamCMD output."""
    block = _extract_app_block(output, app_id)
    try:
        data = vdf.loads(block)
    except Exception as error:
        raise SteamCMDError(f"Could not parse SteamCMD app information: {error}") from error

    app_info = data.get(str(app_id))
    if not isinstance(app_info, dict):
        raise SteamCMDError(f"SteamCMD did not return valid app information for App ID {app_id}.")
    return app_info


def public_branches(app_info: dict[str, Any]) -> list[str]:
    """Return branch names that do not require a branch password."""
    depots = app_info.get("depots", {})
    branches = depots.get("branches", {}) if isinstance(depots, dict) else {}
    if not isinstance(branches, dict):
        return []

    result: list[str] = []
    for name, metadata in branches.items():
        if not isinstance(metadata, dict):
            continue
        password_required = str(metadata.get("pwdrequired", "0")).casefold()
        if password_required not in {"0", "false", "no", ""}:
            continue
        result.append("" if name == "public" else str(name))
    return result


def fetch_public_branches(app_id: int, executable: str | None = None) -> list[str]:
    """Run SteamCMD and return the app's public branch names."""
    command = find_steamcmd(executable)
    if command is None:
        if executable:
            message = f"SteamCMD executable '{executable}' was not found."
        else:
            message = "SteamCMD was not found on PATH or in the SGS user install directory."
        raise SteamCMDNotFoundError(
            f"{message} Run 'sgs steamcmd install' to install a user-local copy, "
            "or pass --steamcmd."
        )

    try:
        result = subprocess.run(
            [command, "+app_info_print", str(app_id), "+quit"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    except FileNotFoundError as error:
        raise SteamCMDNotFoundError(
            f"SteamCMD executable was not found: {command}. "
            "Run 'sgs steamcmd install' to install a user-local copy."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise SteamCMDError("SteamCMD timed out while retrieving app information.") from error
    except OSError as error:
        raise SteamCMDError(f"Could not run SteamCMD: {error}") from error

    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0:
        raise SteamCMDError(
            f"SteamCMD exited with status {result.returncode}: {output.strip()[-1000:]}"
        )
    return public_branches(parse_app_info(output, app_id))


def get_available_branches(
    app_id: int,
    game_state: dict[str, Any],
    executable: str | None = None,
    force_refresh: bool = False,
    now: int | None = None,
    use_cache: bool = False,
) -> tuple[list[str], str | None]:
    """Use the daily cache, refreshing it through SteamCMD when needed."""
    timestamp = int(time.time()) if now is None else now
    cache = game_state.get("branch_cache", {})
    cached_branches = cache.get("branches", []) if isinstance(cache, dict) else []
    fetched_at = cache.get("fetched_at", 0) if isinstance(cache, dict) else 0
    if not isinstance(cached_branches, list) or not all(
        isinstance(branch, str) for branch in cached_branches
    ):
        cached_branches = []
    if not isinstance(fetched_at, int):
        fetched_at = 0

    cache_age = timestamp - fetched_at
    cache_is_fresh = 0 <= cache_age < CACHE_TTL_SECONDS
    if use_cache and not force_refresh and cached_branches:
        if cache_is_fresh:
            return cached_branches, None
        return cached_branches, "Using cached branch data as requested; it may be stale."

    if not force_refresh and cached_branches and cache_is_fresh:
        if find_steamcmd(executable) is None:
            return cached_branches, (
                "SteamCMD is missing; using cached branch data. "
                "Run 'sgs steamcmd install' to install it for this user."
            )
        return cached_branches, None

    try:
        branches = fetch_public_branches(app_id, executable)
    except SteamCMDError as error:
        if cached_branches and not force_refresh:
            return cached_branches, f"SteamCMD refresh failed; using cached branches. {error}"
        raise

    game_state["branch_cache"] = {"fetched_at": timestamp, "branches": branches}
    return branches, None
