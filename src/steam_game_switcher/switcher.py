"""Branch selection and appmanifest update logic."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from .errors import SwitcherError


@dataclass(frozen=True)
class SwitchPlan:
    """A computed change that has not yet been written to disk."""

    old_branch: str
    new_branch: str
    old_install_dir: str
    new_install_dir: str
    manifest: dict[str, Any]


def branch_label(branch: str) -> str:
    """Return a human-readable branch label for the public branch too."""
    return branch or "public"


def active_branch(manifest: dict[str, Any]) -> str:
    app_state = manifest.get("AppState", {})
    user_config = app_state.get("UserConfig", {}) if isinstance(app_state, dict) else {}
    branch = user_config.get("BetaKey", "") if isinstance(user_config, dict) else ""
    return str(branch or "")


def resolve_branch(branches: list[str], current: str, target: str) -> str:
    """Resolve a branch name, one-based index, next/previous, or legacy token."""
    if not branches:
        raise SwitcherError("No public branches were found for this game.")

    normalized_branches = ["" if branch.casefold() == "public" else branch for branch in branches]
    if len(set(normalized_branches)) != len(normalized_branches):
        raise SwitcherError("Steam returned duplicate branch names.")
    current_index = normalized_branches.index(current) if current in normalized_branches else 0
    requested = target.strip()
    lowered = requested.casefold()

    if lowered in {"next", "0"}:
        return normalized_branches[(current_index + 1) % len(normalized_branches)]
    if lowered in {"previous", "prev", "-"}:
        return normalized_branches[(current_index - 1) % len(normalized_branches)]
    if lowered == "public":
        requested = ""
    elif re.fullmatch(r"-?\d+", requested):
        index = int(requested)
        if index == 0:
            return normalized_branches[(current_index + 1) % len(normalized_branches)]
        if index > 0:
            index -= 1
        if not -len(normalized_branches) <= index < len(normalized_branches):
            raise SwitcherError(
                f"Branch index {target!r} is out of range for {len(normalized_branches)} branches."
            )
        return normalized_branches[index]

    if requested not in normalized_branches:
        available = ", ".join(branch_label(branch) for branch in normalized_branches)
        raise SwitcherError(f"Unknown branch {target!r}. Available branches: {available}")
    return requested


def _safe_install_dir(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or PurePath(name).name != name
        or "/" in name
        or "\\" in name
    ):
        raise SwitcherError(f"Install directory must be a single folder name, got {name!r}.")
    return name


def _default_install_dir(game_name: str, branch: str) -> str:
    if not branch:
        return _safe_install_dir(game_name)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", branch).strip("-").lower()
    if not slug:
        slug = "branch"
    return _safe_install_dir(f"{game_name}-{slug}")


def build_switch_plan(
    manifest: dict[str, Any],
    game_state: dict[str, Any],
    branches: list[str],
    target: str,
    separate_install_dirs: bool,
) -> SwitchPlan:
    """Build a new appmanifest without modifying the input manifest."""
    original_app_state = manifest.get("AppState")
    if not isinstance(original_app_state, dict):
        raise SwitcherError("The manifest is missing its 'AppState' section.")

    game_name = str(original_app_state.get("name") or "Game")
    current_install_dir = str(original_app_state.get("installdir") or game_name)
    old_branch = active_branch(manifest)
    new_branch = resolve_branch(branches, old_branch, target)

    install_dirs = game_state.setdefault("install_dirs", {})
    if separate_install_dirs and old_branch not in install_dirs:
        install_dirs[old_branch] = _safe_install_dir(current_install_dir)
    new_manifest = copy.deepcopy(manifest)

    app_state = new_manifest.setdefault("AppState", {})
    app_state.setdefault("UserConfig", {})["BetaKey"] = new_branch
    app_state.setdefault("MountedConfig", {})["BetaKey"] = new_branch

    if separate_install_dirs:
        configured_dir = install_dirs.get(new_branch)
        new_install_dir = (
            _safe_install_dir(configured_dir)
            if isinstance(configured_dir, str)
            else _default_install_dir(game_name, new_branch)
        )
    else:
        new_install_dir = current_install_dir
    app_state["installdir"] = new_install_dir

    return SwitchPlan(
        old_branch=old_branch,
        new_branch=new_branch,
        old_install_dir=current_install_dir,
        new_install_dir=new_install_dir,
        manifest=new_manifest,
    )
