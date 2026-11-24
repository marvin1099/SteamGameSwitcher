"""Generate native desktop launchers for switching Steam game branches."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from .desktop_integration import application_icon_path, applications_directory
from .errors import SwitcherError
from .switcher import branch_label, resolve_branch

_EXTENSIONS = {"Linux": ".desktop", "Windows": ".vbs", "Darwin": ".command"}


def default_shortcut_directory(platform_name: str | None = None) -> Path:
    """Return the user's platform-specific application launcher directory."""
    system = platform_name or platform.system()
    if system == "Linux":
        return applications_directory()

    if system == "Windows":
        roaming_data = os.environ.get("APPDATA")
        data_home = (
            Path(roaming_data).expanduser() if roaming_data else Path.home() / "AppData" / "Roaming"
        )
        return data_home / "Microsoft" / "Windows" / "Start Menu" / "Programs"

    if system == "Darwin":
        return Path.home() / "Applications"

    return Path.home() / "Applications"


def _desktop_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    )


def _desktop_argument(value: str) -> str:
    if "\n" in value or "\r" in value or "\0" in value:
        raise SwitcherError("Shortcut command arguments cannot contain newlines or NUL characters.")
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def _vbscript_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _command_arguments(
    executable: str,
    app_id: int,
    manifest_path: Path,
    config_path: Path,
    branch: str,
    steamcmd: str | None,
    sgs_executable: str | None,
) -> list[str]:
    if sgs_executable:
        arguments = [str(Path(sgs_executable).expanduser().absolute())]
    else:
        arguments = [
            str(Path(executable).expanduser().absolute()),
            "-m",
            "steam_game_switcher",
        ]
    arguments.extend(
        (
            "--app-id",
            str(app_id),
            "--manifest",
            str(manifest_path.expanduser().absolute()),
            "--config",
            str(config_path.expanduser().absolute()),
        )
    )
    if steamcmd:
        arguments.extend(("--steamcmd", steamcmd))
    arguments.extend(("switch", "--", branch or "public"))
    return arguments


def _render_shortcut(
    platform_name: str,
    name: str,
    arguments: list[str],
) -> tuple[str, str]:
    try:
        extension = _EXTENSIONS[platform_name]
    except KeyError as error:
        raise SwitcherError(f"Shortcut generation is not supported on {platform_name}.") from error

    if any(any(character in argument for character in "\0\r\n") for argument in arguments):
        raise SwitcherError("Shortcut command arguments cannot contain newlines or NUL characters.")

    if platform_name == "Linux":
        command = " ".join(_desktop_argument(argument) for argument in arguments)
        contents = "\n".join(
            (
                "[Desktop Entry]",
                "Version=1.0",
                "Type=Application",
                f"Name={_desktop_value(name)}",
                f"Comment={_desktop_value(name)}",
                f"Exec={command}",
                f"Icon={application_icon_path().resolve()}",
                "Terminal=false",
                "Categories=Game;",
                "",
            )
        )
        return extension, contents

    if platform_name == "Windows":
        command = subprocess.list2cmdline(arguments)
        contents = (
            'Set shell = CreateObject("WScript.Shell")\n'
            f"shell.Run {_vbscript_string(command)}, 0, False\n"
        )
        return extension, contents

    contents = f"#!/bin/sh\nexec {shlex.join(arguments)}\n"
    return extension, contents


def _branch_slugs(branches: list[str]) -> dict[str, str]:
    base_slugs = {}
    for branch in branches:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", branch_label(branch)).strip("-_").lower() or "branch"
        if len(slug) > 100:
            branch_hash = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:10]
            slug = f"{slug[:89].rstrip('-_')}-{branch_hash}"
        base_slugs[branch] = slug
    slug_counts: dict[str, int] = {}
    for slug in base_slugs.values():
        slug_counts[slug.casefold()] = slug_counts.get(slug.casefold(), 0) + 1

    result = {}
    for branch, slug in base_slugs.items():
        if slug_counts[slug.casefold()] > 1:
            branch_hash = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:10]
            slug = f"{slug}-{branch_hash}"
        result[branch] = slug
    return result


def generate_shortcuts(
    branches: list[str],
    selections: list[str],
    current_branch: str,
    app_id: int,
    game_name: str,
    manifest_path: Path,
    config_path: Path,
    output_directory: Path,
    executable: str,
    steamcmd: str | None = None,
    platform_name: str | None = None,
    force: bool = False,
    sgs_executable: str | None = None,
) -> list[Path]:
    """Create one native launcher per selected branch, returning their paths."""
    system = platform_name or platform.system()
    try:
        extension = _EXTENSIONS[system]
    except KeyError as error:
        raise SwitcherError(f"Shortcut generation is not supported on {system}.") from error

    if not selections:
        raise SwitcherError("Select one or more branches for shortcut generation.")

    selected_branches: list[str] = []
    for selection in selections:
        branch = resolve_branch(branches, current_branch, selection)
        if branch not in selected_branches:
            selected_branches.append(branch)

    slugs = _branch_slugs(selected_branches)
    output_path = output_directory.expanduser().absolute()
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SwitcherError(
            f"Could not create shortcut directory '{output_path}': {error}"
        ) from error

    targets = {
        branch: output_path / f"sgs-{app_id}-{slugs[branch]}{extension}"
        for branch in selected_branches
    }
    if not force:
        existing = [path for path in targets.values() if path.exists() or path.is_symlink()]
        if existing:
            joined = ", ".join(str(path) for path in existing)
            raise SwitcherError(
                f"Shortcut file already exists: {joined}. Pass --force to replace it."
            )

    rendered_shortcuts: list[tuple[Path, str]] = []
    for branch, target_path in targets.items():
        name = f"Switch {game_name} to {branch_label(branch)}"
        arguments = _command_arguments(
            executable,
            app_id,
            manifest_path,
            config_path,
            branch,
            steamcmd,
            sgs_executable,
        )
        _, contents = _render_shortcut(system, name, arguments)
        rendered_shortcuts.append((target_path, contents))

    created: list[Path] = []
    encoding = "utf-16" if system == "Windows" else "utf-8"
    executable_file = system in {"Linux", "Darwin"}
    for target_path, contents in rendered_shortcuts:
        temporary_path: Path | None = None
        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target_path.name}.", suffix=".tmp", dir=output_path
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(file_descriptor, "w", encoding=encoding, newline="\n") as output:
                output.write(contents)
            if executable_file:
                temporary_path.chmod(0o755)
            os.replace(temporary_path, target_path)
        except OSError as error:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise SwitcherError(f"Could not create shortcut '{target_path}': {error}") from error
        created.append(target_path)
    return created
