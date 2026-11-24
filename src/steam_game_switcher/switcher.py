"""Branch selection and appmanifest update logic."""

from __future__ import annotations

import copy
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from .errors import SwitcherError

_WINDOWS_INVALID_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
DEFAULT_INSTALL_DIR_COMPONENT_LIMIT = 255


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


def branch_changed_outside_sgs(
    current_branch: str,
    game_state: dict[str, Any],
) -> bool:
    """Detect a branch changed in Steam since SGS last managed this game's manifest."""
    last_managed_branch = game_state.get("last_managed_branch")
    return isinstance(last_managed_branch, str) and current_branch != last_managed_branch


def resolve_branch(branches: list[str], current: str, target: str) -> str:
    """Resolve a branch name, one-based index, next/previous, or legacy token."""
    if not branches:
        raise SwitcherError("No public branches were found for this game.")

    normalized_branches = ["" if branch.casefold() == "public" else branch for branch in branches]
    if len(set(normalized_branches)) != len(normalized_branches):
        raise SwitcherError("Steam returned duplicate branch names.")
    current_index = normalized_branches.index(current) if current in normalized_branches else None
    requested = target.strip()
    lowered = requested.casefold()

    if lowered in {"next", "0"}:
        next_index = 0 if current_index is None else (current_index + 1) % len(normalized_branches)
        return normalized_branches[next_index]
    if lowered in {"previous", "prev", "-"}:
        previous_index = (
            -1 if current_index is None else (current_index - 1) % len(normalized_branches)
        )
        return normalized_branches[previous_index]
    if lowered == "public":
        requested = ""
    elif re.fullmatch(r"-?\d+", requested):
        index = int(requested)
        if index == 0:
            next_index = (
                0 if current_index is None else (current_index + 1) % len(normalized_branches)
            )
            return normalized_branches[next_index]
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


def _component_length(name: str) -> int:
    if os.name == "nt":
        return len(name.encode("utf-16-le")) // 2
    return len(name.encode("utf-8"))


def _component_length_unit() -> str:
    return "UTF-16 code units" if os.name == "nt" else "UTF-8 bytes"


def _safe_install_dir(name: str, max_component_length: int) -> str:
    try:
        component_length = _component_length(name)
    except UnicodeEncodeError as error:
        raise SwitcherError("Install directory must contain valid Unicode characters.") from error
    if component_length > max_component_length:
        raise SwitcherError(
            f"Install directory exceeds this filesystem's component limit of "
            f"{max_component_length} {_component_length_unit()}."
        )
    if (
        not name
        or name in {".", ".."}
        or PurePath(name).name != name
        or _WINDOWS_INVALID_CHARS.search(name)
        or name[-1] in {".", " "}
        or name.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise SwitcherError(
            f"Install directory must be a portable, single folder name, got {name!r}."
        )
    return name


def _safe_generated_component(name: str, max_component_length: int) -> str:
    result = _WINDOWS_INVALID_CHARS.sub("-", name).rstrip(". ").strip()
    if not result or result in {".", ".."}:
        result = "Game"
    if result.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        result = f"Game-{result}"
    try:
        encoded_result = result.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SwitcherError("Generated install directory contains invalid Unicode.") from error
    if _component_length(result) > max_component_length:
        digest = hashlib.sha256(encoded_result).hexdigest()[:10]
        suffix = f"-{digest}"
        prefix_limit = max_component_length - _component_length(suffix)
        prefix: list[str] = []
        prefix_length = 0
        for character in result:
            character_length = _component_length(character)
            if prefix_length + character_length > prefix_limit:
                break
            prefix.append(character)
            prefix_length += character_length
        result = f"{''.join(prefix).rstrip('. ')}{suffix}"
    return _safe_install_dir(result, max_component_length)


def _branch_slug(branch: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", branch).strip("-").lower()
    if not slug:
        slug = "branch"
    return slug


def _default_install_dir(
    game_name: str,
    branch: str,
    branches: list[str],
    max_component_length: int,
) -> str:
    base = _safe_generated_component(game_name, max_component_length)
    if not branch:
        return base

    slug = _branch_slug(branch)
    slug_collides = any(
        other != branch and _branch_slug(other) == slug for other in branches if other
    )
    if slug_collides:
        branch_hash = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:10]
        slug = f"{slug}-{branch_hash}"
    return _safe_generated_component(f"{base}-{slug}", max_component_length)


def _install_dir_for_branch(
    game_name: str,
    branch: str,
    branches: list[str],
    install_dirs: dict[str, Any],
    max_component_length: int,
) -> str:
    configured_dir = install_dirs.get(branch)
    uses_custom_dir = isinstance(configured_dir, str)
    if uses_custom_dir:
        candidate = _safe_install_dir(configured_dir, max_component_length)
    else:
        candidate = _default_install_dir(game_name, branch, branches, max_component_length)

    other_dirs: set[str] = set()
    for other_branch in set(branches).union(install_dirs):
        if other_branch == branch:
            continue
        other_configured = install_dirs.get(other_branch)
        if isinstance(other_configured, str):
            other_dir = _safe_install_dir(other_configured, max_component_length)
        else:
            other_dir = _default_install_dir(
                game_name,
                other_branch,
                branches,
                max_component_length,
            )
        other_dirs.add(other_dir.casefold())

    if candidate.casefold() in other_dirs:
        if uses_custom_dir:
            raise SwitcherError(
                f"Custom install directory {candidate!r} for branch {branch!r} "
                "is already used by another branch."
            )
        label = _branch_slug(branch) if branch else "public"
        branch_hash = hashlib.sha256(branch.encode("utf-8")).hexdigest()
        candidate_base = _safe_generated_component(game_name, max_component_length)
        candidate_name = f"{candidate_base}-{label}-{branch_hash[:10]}"
        candidate = _safe_generated_component(candidate_name, max_component_length)
        if candidate.casefold() in other_dirs:
            raise SwitcherError(f"Could not generate a unique install directory for {branch!r}.")
    return candidate


def build_switch_plan(
    manifest: dict[str, Any],
    game_state: dict[str, Any],
    branches: list[str],
    target: str,
    separate_install_dirs: bool,
    max_component_length: int = DEFAULT_INSTALL_DIR_COMPONENT_LIMIT,
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
    last_managed_branch = game_state.get("last_managed_branch")
    last_managed_install_dir = game_state.get("last_managed_install_dir")
    externally_changed = branch_changed_outside_sgs(old_branch, game_state)
    if separate_install_dirs:
        if isinstance(last_managed_branch, str) and isinstance(last_managed_install_dir, str):
            install_dirs.setdefault(
                last_managed_branch,
                _safe_install_dir(last_managed_install_dir, max_component_length),
            )
        if old_branch not in install_dirs and not externally_changed:
            install_dirs[old_branch] = _safe_install_dir(current_install_dir, max_component_length)
    new_manifest = copy.deepcopy(manifest)

    app_state = new_manifest.setdefault("AppState", {})
    app_state.setdefault("UserConfig", {})["BetaKey"] = new_branch
    app_state.setdefault("MountedConfig", {})["BetaKey"] = new_branch

    if separate_install_dirs:
        new_install_dir = _install_dir_for_branch(
            game_name,
            new_branch,
            branches,
            install_dirs,
            max_component_length,
        )
    else:
        new_install_dir = current_install_dir
    if separate_install_dirs:
        install_dirs[new_branch] = new_install_dir
    app_state["installdir"] = new_install_dir

    return SwitchPlan(
        old_branch=old_branch,
        new_branch=new_branch,
        old_install_dir=current_install_dir,
        new_install_dir=new_install_dir,
        manifest=new_manifest,
    )
