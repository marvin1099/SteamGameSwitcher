"""Command-line interface for Steam Game Switcher."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .acf import load_acf, save_acf_atomic
from .backups import (
    add_backup,
    backup_store_path,
    find_backup,
    load_backup_store,
    save_backup_store,
)
from .errors import SwitcherError
from .paths import find_manifest
from .state import default_config_path, load_state, save_state
from .steamcmd import get_available_branches
from .switcher import active_branch, branch_label, build_switch_plan

DEFAULT_APP_ID = 526870


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steam-game-switcher",
        description="List and switch public Steam branches by editing a local appmanifest.",
    )
    parser.add_argument(
        "--app-id",
        type=_positive_int,
        default=DEFAULT_APP_ID,
        help="Steam App ID (default: %(default)s)",
    )
    parser.add_argument(
        "--steamapps",
        type=Path,
        help="Steam steamapps directory (detected automatically by default)",
    )
    parser.add_argument("--manifest", type=Path, help="path to appmanifest_<app-id>.acf")
    parser.add_argument(
        "--config", type=Path, default=default_config_path(), help="config/state JSON file"
    )
    parser.add_argument("--steamcmd", help="SteamCMD executable (default: search PATH)")
    parser.add_argument("--refresh", action="store_true", help="refresh branch data from SteamCMD")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("branches", help="list public branches")
    commands.add_parser("status", help="show the installed branch and manifest")

    switch = commands.add_parser("switch", help="switch to a branch (default: next branch)")
    switch.add_argument(
        "target",
        nargs="?",
        default="next",
        help="next, previous, a one-based index, or a branch name (default: next)",
    )
    switch.add_argument(
        "--dry-run", action="store_true", help="show the change without writing files"
    )
    folder_options = switch.add_mutually_exclusive_group()
    folder_options.add_argument(
        "--separate-folders",
        action="store_true",
        help="enable separate install directories for this game's setting",
    )
    folder_options.add_argument(
        "--shared-folder",
        action="store_true",
        help="disable separate install directories for this game",
    )

    backups = commands.add_parser("backups", help="list saved appmanifest backups")
    backups.add_argument("--all", action="store_true", help="show backups for every App ID")

    restore = commands.add_parser("restore", help="restore an appmanifest backup by ID")
    restore.add_argument("backup_id", help="ID shown by the backups command")
    restore.add_argument("--dry-run", action="store_true", help="preview without writing files")
    return parser


def _load_and_validate_manifest(path: Path, app_id: int) -> dict:
    manifest = load_acf(path)
    app_state = manifest.get("AppState")
    if not isinstance(app_state, dict):
        raise SwitcherError(f"Manifest '{path}' is missing its 'AppState' section.")
    manifest_app_id = app_state.get("appid")
    if manifest_app_id is not None and str(manifest_app_id) != str(app_id):
        raise SwitcherError(
            f"Manifest '{path}' is for App ID {manifest_app_id}, not the requested App ID {app_id}."
        )
    if manifest_app_id is None:
        app_state["appid"] = str(app_id)
    if not app_state.get("installdir"):
        raise SwitcherError(f"Manifest '{path}' does not contain an install directory.")
    return manifest


def _manifest_path(args: argparse.Namespace) -> Path:
    return find_manifest(args.app_id, steamapps=args.steamapps, manifest=args.manifest)


def _run_branches(args: argparse.Namespace) -> int:
    root_state, game_state = load_state(args.config, args.app_id)
    branches, warning = get_available_branches(
        args.app_id, game_state, args.steamcmd, force_refresh=args.refresh
    )
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    if not branches:
        raise SwitcherError("SteamCMD returned no public branches for this game.")
    for index, branch in enumerate(branches, start=1):
        print(f"{index:>2}. {branch_label(branch)}")
    save_state(args.config, root_state)
    return 0


def _run_status(args: argparse.Namespace) -> int:
    path = _manifest_path(args)
    manifest = _load_and_validate_manifest(path, args.app_id)
    app_state = manifest["AppState"]
    branch = active_branch(manifest)
    print(f"Game: {app_state.get('name', 'Unknown game')} (App ID {args.app_id})")
    print(f"Branch: {branch_label(branch)}")
    print(f"Install directory: {app_state['installdir']}")
    _, game_state = load_state(args.config, args.app_id)
    setting = "enabled" if game_state["separate_install_dirs"] else "disabled"
    print(f"Separate install directories: {setting}")
    print(f"Manifest: {path}")
    return 0


def _run_switch(args: argparse.Namespace) -> int:
    manifest_path = _manifest_path(args)
    manifest = _load_and_validate_manifest(manifest_path, args.app_id)
    root_state, game_state = load_state(args.config, args.app_id)
    branches, warning = get_available_branches(
        args.app_id, game_state, args.steamcmd, force_refresh=args.refresh
    )
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)

    if args.separate_folders:
        game_state["separate_install_dirs"] = True
    elif args.shared_folder:
        game_state["separate_install_dirs"] = False
    separate_dirs = bool(game_state.get("separate_install_dirs", True))
    plan = build_switch_plan(
        manifest,
        game_state,
        branches,
        args.target,
        separate_install_dirs=separate_dirs,
    )

    if plan.manifest == manifest:
        print(f"Already on {branch_label(plan.new_branch)}; no manifest changes needed.")
        if not args.dry_run:
            save_state(args.config, root_state)
        return 0

    print(
        f"Switch {branch_label(plan.old_branch)} -> {branch_label(plan.new_branch)} "
        f"(install directory: {plan.old_install_dir} -> {plan.new_install_dir})"
    )
    if args.dry_run:
        print("Dry run: no files were changed.")
        return 0

    backup_path = backup_store_path(args.config)
    backup_store = load_backup_store(backup_path)
    backup_id, backup_created = add_backup(
        backup_store,
        args.app_id,
        manifest_path,
        manifest,
        plan.old_branch,
    )
    if backup_created:
        save_backup_store(backup_path, backup_store)
    save_acf_atomic(manifest_path, plan.manifest)
    save_state(args.config, root_state)
    print(f"Manifest updated: {manifest_path}")
    if backup_created:
        print(f"Backup saved as {backup_id} in {backup_path}")
    else:
        print(f"Backup {backup_id} already contains this manifest; duplicate not saved.")
    print("Steam may need to be restarted to notice the branch change.")
    return 0


def _run_backups(args: argparse.Namespace) -> int:
    path = backup_store_path(args.config)
    store = load_backup_store(path)
    entries = store["entries"]
    if not args.all:
        entries = [entry for entry in entries if entry.get("app_id") == args.app_id]
    entries = sorted(entries, key=lambda entry: entry.get("created_at", ""), reverse=True)
    if not entries:
        print("No backups found.")
        return 0

    for entry in entries:
        branch = branch_label(str(entry.get("branch") or ""))
        print(
            f"{entry.get('id', '?')}  App {entry.get('app_id', '?')}  {branch}  "
            f"{entry.get('created_at', 'unknown time')}  {entry.get('manifest_path', '')}"
        )
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    backup_path = backup_store_path(args.config)
    store = load_backup_store(backup_path)
    entry = find_backup(store, args.backup_id)
    app_id = entry["app_id"]
    saved_data = entry["data"]

    if args.manifest is not None:
        manifest_path = args.manifest.expanduser().resolve()
    elif args.steamapps is not None:
        manifest_path = (args.steamapps.expanduser() / f"appmanifest_{app_id}.acf").resolve()
    else:
        manifest_path = Path(entry["manifest_path"]).expanduser().resolve()

    current_data = None
    if manifest_path.exists():
        current_data = load_acf(manifest_path)
        current_app_state = current_data.get("AppState")
        if not isinstance(current_app_state, dict):
            raise SwitcherError(f"Manifest '{manifest_path}' is missing its 'AppState' section.")
        current_app_id = current_app_state.get("appid")
        if current_app_id is not None and str(current_app_id) != str(app_id):
            raise SwitcherError(
                f"Manifest '{manifest_path}' is for App ID {current_app_id}, not {app_id}."
            )
        if current_data == saved_data:
            print(f"Manifest already matches backup {args.backup_id}; no changes needed.")
            return 0

    print(f"Restore backup {args.backup_id} for App ID {app_id} to {manifest_path}")
    if args.dry_run:
        print("Dry run: no files were changed.")
        return 0

    if current_data is not None:
        current_branch = active_branch(current_data)
        _, backup_created = add_backup(store, app_id, manifest_path, current_data, current_branch)
        if backup_created:
            save_backup_store(backup_path, store)
    save_acf_atomic(manifest_path, saved_data)
    print(f"Manifest restored: {manifest_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line application and return its process status."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.manifest is not None and args.steamapps is not None:
            raise SwitcherError("Use either --manifest or --steamapps, not both.")
        if args.command == "branches":
            return _run_branches(args)
        if args.command == "status":
            return _run_status(args)
        if args.command == "switch":
            return _run_switch(args)
        if args.command == "backups":
            return _run_backups(args)
        return _run_restore(args)
    except SwitcherError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
