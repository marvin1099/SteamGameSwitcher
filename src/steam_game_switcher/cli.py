"""Command-line interface for Steam Game Switcher."""

from __future__ import annotations

import argparse
import copy
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from .acf import load_acf, save_acf_atomic
from .backups import (
    add_backup,
    backup_store_path,
    backup_timestamp,
    find_backup,
    load_backup_store,
    save_backup_store,
)
from .errors import SteamCMDNotFoundError, SwitcherError
from .paths import find_manifest, install_dir_component_limit
from .shortcuts import default_shortcut_directory, generate_shortcuts
from .state import default_config_path, load_root_state, load_state, save_state
from .steam_client import (
    SteamShutdown,
    launch_game,
    relaunch_steam,
    shutdown_steam_if_running,
    steam_running_status,
)
from .steamcmd import get_available_branches
from .steamcmd_install import find_steamcmd, install_steamcmd
from .switcher import (
    active_branch,
    branch_changed_outside_sgs,
    branch_label,
    build_switch_plan,
    resolve_branch,
)


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
        prog="sgs",
        description=(
            "Switch Steam branches, inspect game status, manage backups and settings, "
            "and create branch launchers."
        ),
    )
    parser.add_argument(
        "--app-id",
        type=_positive_int,
        default=None,
        help="Steam App ID for this command (defaults to the saved App ID)",
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
    parser.add_argument(
        "--steamcmd",
        help="SteamCMD executable (default: search the SGS user install and PATH)",
    )
    guard_options = parser.add_mutually_exclusive_group()
    guard_options.add_argument(
        "--guard",
        dest="guard",
        action="store_true",
        default=False,
        help="refuse manifest edits if Steam may be running and SGS is not restarting it",
    )
    guard_options.add_argument(
        "--no-guard",
        dest="guard",
        action="store_false",
        help="warn but proceed when Steam is running or its state is unknown (default)",
    )
    branch_cache_options = parser.add_mutually_exclusive_group()
    branch_cache_options.add_argument(
        "--refresh", action="store_true", help="refresh branch data from SteamCMD"
    )
    branch_cache_options.add_argument(
        "--cache",
        action="store_true",
        help="use cached branch data even if expired (fetch if no cache exists)",
    )

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
    switch.add_argument(
        "--install-dir",
        metavar="NAME",
        help="set or replace this branch's install folder and enable separate folders",
    )

    settings = commands.add_parser("settings", help="view or change settings for the selected game")
    folder_settings = settings.add_mutually_exclusive_group()
    folder_settings.add_argument(
        "--separate-folders",
        dest="separate_install_dirs",
        action="store_true",
        default=None,
        help="use a separate install folder for each branch",
    )
    folder_settings.add_argument(
        "--shared-folder",
        dest="separate_install_dirs",
        action="store_false",
        default=None,
        help="use one install folder for every branch",
    )
    settings.add_argument(
        "--restart-steam-on-switch",
        dest="restart_steam",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="save whether Steam should restart after a branch change",
    )
    settings.add_argument(
        "--launch-game-after-switch",
        dest="launch_game",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="save whether to launch the game after a branch change",
    )
    settings.add_argument(
        "--launch-game-when-unchanged",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="save whether to launch when the requested branch is already active",
    )

    defaults = commands.add_parser(
        "defaults", help="view or change the default App ID and new-game settings"
    )
    defaults.add_argument(
        "--app-id",
        "--default-app-id",
        dest="default_app_id",
        type=_positive_int,
        help="set the App ID used by commands when --app-id is omitted",
    )
    folder_defaults = defaults.add_mutually_exclusive_group()
    folder_defaults.add_argument(
        "--separate-folders",
        dest="separate_install_dirs",
        action="store_true",
        default=None,
        help="use separate install folders for new games",
    )
    folder_defaults.add_argument(
        "--shared-folder",
        dest="separate_install_dirs",
        action="store_false",
        default=None,
        help="use one install folder for new games",
    )
    defaults.add_argument(
        "--restart-steam",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="set the default Steam restart preference for new games",
    )
    defaults.add_argument(
        "--launch-game",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="set the default Steam URI launch preference for new games",
    )
    defaults.add_argument(
        "--launch-game-when-unchanged",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="set the default launch preference when a branch is already active",
    )

    backup = commands.add_parser("backup", help="list, restore, or delete appmanifest backups")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backups = backup_commands.add_parser("list", help="list saved appmanifest backups")
    backups.add_argument(
        "--app-id",
        type=_positive_int,
        default=argparse.SUPPRESS,
        help="filter by Steam App ID (default: global --app-id value)",
    )
    backups.add_argument("--all", action="store_true", help="show backups for every App ID")

    restore = backup_commands.add_parser(
        "restore", help="restore an appmanifest backup by number or ID"
    )
    restore.add_argument("backup_id", help="number shown by 'backup list', or a stable backup ID")
    restore.add_argument(
        "--app-id",
        type=_positive_int,
        default=argparse.SUPPRESS,
        help="filter numbered backups by Steam App ID (default: global --app-id value)",
    )
    restore.add_argument(
        "--global-numbering",
        action="store_true",
        help="select by number across backups for every App ID",
    )
    restore.add_argument("--dry-run", action="store_true", help="preview without writing files")

    delete = backup_commands.add_parser(
        "delete", help="delete a saved appmanifest backup by number or ID"
    )
    delete.add_argument("backup_ref", help="number shown by 'backup list', or a stable backup ID")
    delete.add_argument(
        "--app-id",
        type=_positive_int,
        default=argparse.SUPPRESS,
        help="filter numbered backups by Steam App ID (default: global --app-id value)",
    )
    delete.add_argument(
        "--global-numbering",
        action="store_true",
        help="select by number across backups for every App ID",
    )
    delete.add_argument(
        "--yes", "-y", action="store_true", help="delete without asking for confirmation"
    )

    steamcmd = commands.add_parser("steamcmd", help="install or repair the user-local SteamCMD")
    steamcmd_commands = steamcmd.add_subparsers(dest="steamcmd_command", required=True)
    steamcmd_commands.add_parser("install", help="install SteamCMD for the current user")
    steamcmd_commands.add_parser("repair", help="replace the current user's SteamCMD install")
    commands.add_parser("gui", help="open the optional graphical interface")
    shortcuts = commands.add_parser(
        "shortcuts", help="generate launchers for selected branch switches"
    )
    shortcuts.add_argument(
        "targets",
        nargs="+",
        help="branch names or indices (negative indices count from the end)",
    )
    shortcuts.add_argument(
        "--output",
        type=Path,
        default=default_shortcut_directory(),
        help="output directory (default: the user's application launcher folder)",
    )
    shortcuts.add_argument("--force", action="store_true", help="replace existing shortcut files")
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
        args.app_id,
        game_state,
        args.steamcmd,
        force_refresh=args.refresh,
        use_cache=args.cache,
    )
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    if not branches:
        raise SwitcherError("SteamCMD returned no public branches for this game.")
    for index, branch in enumerate(branches, start=1):
        print(f"{index:>2}. {branch_label(branch)}")
    save_state(args.config, root_state)
    return 0


def _run_shortcuts(args: argparse.Namespace) -> int:
    manifest_path = _manifest_path(args)
    manifest = _load_and_validate_manifest(manifest_path, args.app_id)
    root_state, game_state = load_state(args.config, args.app_id)
    branches, warning = get_available_branches(
        args.app_id,
        game_state,
        args.steamcmd,
        force_refresh=args.refresh,
        use_cache=args.cache,
    )
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    if not branches:
        raise SwitcherError("SteamCMD returned no public branches for this game.")

    app_state = manifest["AppState"]
    shortcut_steamcmd = args.steamcmd
    if shortcut_steamcmd:
        shortcut_steamcmd = find_steamcmd(shortcut_steamcmd) or shortcut_steamcmd
    created = generate_shortcuts(
        branches=branches,
        selections=args.targets,
        current_branch=active_branch(manifest),
        app_id=args.app_id,
        game_name=str(app_state.get("name") or "Game"),
        manifest_path=manifest_path,
        config_path=args.config.expanduser().resolve(),
        output_directory=args.output,
        executable=sys.executable,
        steamcmd=shortcut_steamcmd,
        force=args.force,
        sgs_executable=shutil.which("sgs"),
    )
    save_state(args.config, root_state)
    print(f"Shortcut location: {created[0].parent}")
    for shortcut in created:
        print(f"Created shortcut: {shortcut}")
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
    restart_setting = "enabled" if game_state["restart_steam_on_switch"] else "disabled"
    launch_setting = "enabled" if game_state["launch_game_after_switch"] else "disabled"
    unchanged_launch_setting = "enabled" if game_state["launch_game_when_unchanged"] else "disabled"
    print(f"Restart Steam after switch: {restart_setting}")
    print(f"Launch game after switch: {launch_setting}")
    print(f"Launch game when branch is unchanged: {unchanged_launch_setting}")
    print(f"Manifest: {path}")
    return 0


def _run_settings(args: argparse.Namespace) -> int:
    """View or save per-game preferences without touching the manifest or Steam."""
    root_state, game_state = load_state(args.config, args.app_id)
    updates = {
        "separate_install_dirs": args.separate_install_dirs,
        "restart_steam_on_switch": args.restart_steam,
        "launch_game_after_switch": args.launch_game,
        "launch_game_when_unchanged": args.launch_game_when_unchanged,
    }
    changed = False
    for key, value in updates.items():
        if value is not None:
            game_state[key] = value
            changed = True
    if changed:
        save_state(args.config, root_state)

    print(f"Settings for App ID {args.app_id}:")
    separate_label = "enabled" if game_state["separate_install_dirs"] else "disabled"
    restart_label = "enabled" if game_state["restart_steam_on_switch"] else "disabled"
    launch_label = "enabled" if game_state["launch_game_after_switch"] else "disabled"
    unchanged_label = "enabled" if game_state["launch_game_when_unchanged"] else "disabled"
    print(f"  Separate folders: {separate_label}")
    print(f"  Restart Steam after branch change: {restart_label}")
    print(f"  Launch game after branch change: {launch_label}")
    print(f"  Launch game when branch is unchanged: {unchanged_label}")
    if changed:
        print(f"Saved settings to: {args.config.expanduser().resolve()}")
    return 0


def _run_defaults(args: argparse.Namespace) -> int:
    root_state = load_root_state(args.config)
    defaults = root_state["defaults"]
    if args.default_app_id is not None:
        root_state["default_app_id"] = args.default_app_id
    updates = {
        "separate_install_dirs": args.separate_install_dirs,
        "restart_steam_on_switch": args.restart_steam,
        "launch_game_after_switch": args.launch_game,
        "launch_game_when_unchanged": args.launch_game_when_unchanged,
    }
    changed = args.default_app_id is not None
    for key, value in updates.items():
        if value is not None:
            defaults[key] = value
            changed = True
    if changed:
        save_state(args.config, root_state)

    print(f"Default App ID: {root_state['default_app_id']}")
    print("Defaults for new games:")
    print(f"  Separate folders: {'enabled' if defaults['separate_install_dirs'] else 'disabled'}")
    restart_label = "enabled" if defaults["restart_steam_on_switch"] else "disabled"
    launch_label = "enabled" if defaults["launch_game_after_switch"] else "disabled"
    unchanged_launch_label = "enabled" if defaults["launch_game_when_unchanged"] else "disabled"
    print(f"  Restart Steam after switch: {restart_label}")
    print(f"  Launch game after switch: {launch_label}")
    print(f"  Launch game when branch is unchanged: {unchanged_launch_label}")
    if changed:
        print(f"Saved defaults to: {args.config.expanduser().resolve()}")
    return 0


def _run_switch(args: argparse.Namespace) -> int:
    manifest_path = _manifest_path(args)
    manifest = _load_and_validate_manifest(manifest_path, args.app_id)
    root_state, game_state = load_state(args.config, args.app_id)
    branches, warning = get_available_branches(
        args.app_id,
        game_state,
        args.steamcmd,
        force_refresh=args.refresh,
        use_cache=args.cache,
    )
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)

    if args.install_dir is not None:
        target_branch = resolve_branch(branches, active_branch(manifest), args.target)
        game_state["install_dirs"][target_branch] = args.install_dir
        game_state["separate_install_dirs"] = True

    separate_dirs = bool(game_state.get("separate_install_dirs", True))
    plan = build_switch_plan(
        manifest,
        game_state,
        branches,
        args.target,
        separate_install_dirs=separate_dirs,
        max_component_length=install_dir_component_limit(manifest_path),
    )
    branch_changed = plan.old_branch != plan.new_branch
    external_branch_change = branch_changed_outside_sgs(plan.old_branch, game_state)
    branch_change_detected = branch_changed or external_branch_change
    manifest_changed = plan.manifest != manifest
    last_managed_branch = game_state.get("last_managed_branch")

    if args.dry_run:
        if not manifest_changed and not branch_change_detected:
            print(f"Already on {branch_label(plan.new_branch)}; no manifest changes needed.")
        else:
            if branch_changed:
                print(
                    f"Switch {branch_label(plan.old_branch)} -> {branch_label(plan.new_branch)} "
                    f"(install directory: {plan.old_install_dir} -> {plan.new_install_dir})"
                )
            elif external_branch_change:
                previous_label = branch_label(last_managed_branch)
                print(
                    f"Complete external branch change {previous_label} -> "
                    f"{branch_label(plan.new_branch)} "
                    f"(install directory: {plan.old_install_dir} -> {plan.new_install_dir})"
                )
            else:
                print(
                    f"Update {branch_label(plan.new_branch)} manifest "
                    f"(install directory: {plan.old_install_dir} -> {plan.new_install_dir})"
                )
            if not manifest_changed:
                print("No manifest changes needed; branch-change actions would still run.")
            print("Dry run: no files were changed.")
        return 0

    game_state["last_managed_branch"] = plan.new_branch
    game_state["last_managed_install_dir"] = plan.new_install_dir

    backup_path = backup_store_path(args.config)
    backup_store = load_backup_store(backup_path)
    backups_changed = _migrate_branch_profiles(game_state, backup_store, args.app_id, manifest_path)

    if not manifest_changed and not branch_change_detected:
        print(f"Already on {branch_label(plan.new_branch)}; no manifest changes needed.")
        if args.install_dir is not None:
            print(
                f"Install directory for {branch_label(plan.new_branch)} saved as "
                f"{plan.new_install_dir}."
            )
        if backups_changed:
            save_backup_store(backup_path, backup_store)
        save_state(args.config, root_state)
        if game_state["launch_game_when_unchanged"]:
            _launch_game(args.app_id)
        return 0

    if branch_changed:
        print(
            f"Switch {branch_label(plan.old_branch)} -> {branch_label(plan.new_branch)} "
            f"(install directory: {plan.old_install_dir} -> {plan.new_install_dir})"
        )
    elif external_branch_change:
        previous_label = branch_label(last_managed_branch)
        print(
            f"Complete external branch change {previous_label} -> "
            f"{branch_label(plan.new_branch)} "
            f"(install directory: {plan.old_install_dir} -> {plan.new_install_dir})"
        )
    else:
        print(
            f"Update {branch_label(plan.new_branch)} manifest "
            f"(install directory: {plan.old_install_dir} -> {plan.new_install_dir})"
        )

    steam_shutdown = None
    if branch_change_detected and game_state["restart_steam_on_switch"]:
        steam_shutdown = shutdown_steam_if_running()
        if steam_shutdown.warning:
            raise SwitcherError(f"{steam_shutdown.warning} The branch settings were not completed.")
        if steam_shutdown.was_running:
            print("Steam closed before applying branch settings.")
    elif manifest_changed:
        _warn_steam_state_without_restart(args.guard, "update the manifest")

    backup_id = None
    backup_created = False
    try:
        if manifest_changed:
            backup_id, backup_created = add_backup(
                backup_store,
                args.app_id,
                manifest_path,
                manifest,
                plan.old_branch,
            )
            backups_changed |= backup_created
        if backups_changed:
            save_backup_store(backup_path, backup_store)
        if manifest_changed:
            save_acf_atomic(manifest_path, plan.manifest)
        save_state(args.config, root_state)
    finally:
        if steam_shutdown is not None and steam_shutdown.was_running:
            warning = relaunch_steam(steam_shutdown)
            if warning:
                print(f"Warning: {warning}", file=sys.stderr)
            else:
                print("Steam restarted.")

    if manifest_changed:
        print(f"Manifest updated: {manifest_path}")
        if backup_created:
            print(f"Backup saved as {backup_id} in {backup_path}")
        else:
            print(f"Backup {backup_id} already contains this manifest; duplicate not saved.")
    elif external_branch_change:
        print("Manifest already matches the requested branch settings.")
    else:
        print(f"Manifest updated: {manifest_path}")

    if branch_change_detected:
        if not game_state["restart_steam_on_switch"] and manifest_changed:
            print("Steam may need to be restarted to notice the branch change.")
        _run_post_switch_actions(args.app_id, game_state, steam_shutdown)
    else:
        print("Branch unchanged; Steam was not restarted.")
        if game_state["launch_game_when_unchanged"]:
            _launch_game(args.app_id)
        else:
            print("The game was not launched.")
    return 0


def _warn_steam_state_without_restart(guard: bool, action: str) -> None:
    steam_running, warning = steam_running_status()
    if warning:
        message = f"Could not verify Steam state: {warning.rstrip('.')}"
    elif steam_running:
        message = "Steam is running"
    else:
        return

    if guard:
        raise SwitcherError(f"{message}; --guard prevented the attempt to {action}.")

    print(
        f"Warning: {message}. SGS will {action} without restarting Steam; "
        "the user is responsible for ensuring Steam will not overwrite the manifest.",
        file=sys.stderr,
    )


def _run_post_switch_actions(
    app_id: int, game_state: dict, steam_shutdown: SteamShutdown | None
) -> None:
    """Apply saved game-launch behavior after a real branch change."""
    if game_state["restart_steam_on_switch"] and not (
        steam_shutdown is not None and steam_shutdown.was_running
    ):
        print("Steam was not running; no restart was needed.")

    if game_state["launch_game_after_switch"]:
        _launch_game(app_id)


def _launch_game(app_id: int) -> None:
    """Open the configured game's Steam URI and report any launch issue."""
    warning = launch_game(app_id)
    if warning:
        print(f"Warning: {warning}", file=sys.stderr)
    else:
        print(f"Opened Steam URI: steam://rungameid/{app_id}")


def _run_backups(args: argparse.Namespace) -> int:
    path = backup_store_path(args.config)
    store = load_backup_store(path)
    entries = _ordered_backups(store, args.app_id, args.all)
    if not entries:
        print("No backups found.")
        return 0

    for index, entry in enumerate(entries, start=1):
        branch = branch_label(str(entry.get("branch") or ""))
        print(
            f"{index:>2}. {entry.get('id', '?')}  App {entry.get('app_id', '?')}  {branch}  "
            f"{entry.get('created_at', 'unknown time')}  {entry.get('manifest_path', '')}"
        )
    return 0


def _ordered_backups(store: dict, app_id: int, all_apps: bool) -> list[dict]:
    """Return backups in the same order used for display and number selection."""
    entries = store["entries"]
    if not all_apps:
        entries = [entry for entry in entries if entry.get("app_id") == app_id]
    return sorted(entries, key=backup_timestamp, reverse=True)


def _select_backup(store: dict, selector: str, app_id: int, all_apps: bool) -> dict:
    """Resolve a backup ID or its current numbered position and verify its contents."""
    if any(entry.get("id") == selector for entry in store["entries"]):
        backup_id = selector
    elif selector.isdecimal():
        backup_number = int(selector)
        if backup_number < 1:
            raise SwitcherError("Backup numbers start at 1.")
        entries = _ordered_backups(store, app_id, all_apps)
        if backup_number > len(entries):
            listing_command = (
                "sgs backup list --all" if all_apps else f"sgs backup list --app-id {app_id}"
            )
            raise SwitcherError(
                f"Backup number {backup_number} is out of range; run '{listing_command}' "
                "to see available backups."
            )
        backup_id = str(entries[backup_number - 1].get("id", ""))
    else:
        backup_id = selector
    return find_backup(store, backup_id)


def _migrate_branch_profiles(
    game_state: dict,
    backup_store: dict,
    app_id: int,
    manifest_path: Path,
) -> bool:
    """Move v1 per-branch manifest snapshots into the deduplicated backup store."""
    profiles = game_state.get("profiles")
    if profiles is None:
        return False
    if not isinstance(profiles, dict):
        raise SwitcherError(f"Saved branch profiles for App ID {app_id} are malformed.")

    backups_changed = False
    for branch, profile in profiles.items():
        if not isinstance(profile, dict) or not isinstance(profile.get("AppState"), dict):
            raise SwitcherError(
                f"Saved manifest profile {branch!r} for App ID {app_id} is malformed."
            )
        data = copy.deepcopy(profile)
        app_state = data["AppState"]
        profile_app_id = app_state.get("appid")
        if profile_app_id is not None and str(profile_app_id) != str(app_id):
            raise SwitcherError(
                f"Saved manifest profile {branch!r} belongs to App ID {profile_app_id}, "
                f"not {app_id}."
            )
        app_state.setdefault("appid", str(app_id))
        _, created = add_backup(backup_store, app_id, manifest_path, data, str(branch))
        backups_changed |= created

    game_state.pop("profiles", None)
    return backups_changed


def _run_restore(args: argparse.Namespace) -> int:
    backup_path = backup_store_path(args.config)
    store = load_backup_store(backup_path)
    entry = _select_backup(store, args.backup_id, args.app_id, args.global_numbering)
    backup_id = entry["id"]
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
            print(f"Manifest already matches backup {backup_id}; no changes needed.")
            return 0

    saved_app_state = saved_data.get("AppState")
    saved_install_dir = (
        saved_app_state.get("installdir") if isinstance(saved_app_state, dict) else None
    )
    if not isinstance(saved_install_dir, str) or not saved_install_dir:
        raise SwitcherError(f"Backup '{backup_id}' does not contain a valid install directory.")

    print(f"Restore backup {backup_id} for App ID {app_id} to {manifest_path}")
    if args.dry_run:
        print("Dry run: no files were changed.")
        return 0

    root_state, game_state = load_state(args.config, app_id)
    target_branch = active_branch(saved_data)
    current_branch = active_branch(current_data) if current_data is not None else None
    branch_changed = current_branch is not None and current_branch != target_branch

    steam_shutdown = None
    if branch_changed and game_state["restart_steam_on_switch"]:
        steam_shutdown = shutdown_steam_if_running()
        if steam_shutdown.warning:
            raise SwitcherError(f"{steam_shutdown.warning} The backup was not restored.")
        if steam_shutdown.was_running:
            print("Steam closed before restoring the branch.")
    else:
        _warn_steam_state_without_restart(args.guard, "restore the manifest")

    try:
        if current_data is not None:
            current_branch = active_branch(current_data)
            _, backup_created = add_backup(
                store, app_id, manifest_path, current_data, current_branch
            )
            if backup_created:
                save_backup_store(backup_path, store)
        save_acf_atomic(manifest_path, saved_data)
        game_state["last_managed_branch"] = target_branch
        game_state["last_managed_install_dir"] = saved_install_dir
        if game_state["separate_install_dirs"]:
            game_state["install_dirs"][target_branch] = saved_install_dir
        save_state(args.config, root_state)
    finally:
        if steam_shutdown is not None and steam_shutdown.was_running:
            warning = relaunch_steam(steam_shutdown)
            if warning:
                print(f"Warning: {warning}", file=sys.stderr)
            else:
                print("Steam restarted.")

    print(f"Manifest restored: {manifest_path}")
    if branch_changed:
        _run_post_switch_actions(app_id, game_state, steam_shutdown)
    return 0


def _run_delete(args: argparse.Namespace) -> int:
    backup_path = backup_store_path(args.config)
    store = load_backup_store(backup_path)
    entry = _select_backup(store, args.backup_ref, args.app_id, args.global_numbering)
    backup_id = entry["id"]
    branch = branch_label(str(entry.get("branch") or ""))

    if not args.yes:
        try:
            answer = input(
                f"Delete backup {backup_id} for App ID {entry['app_id']} ({branch})? [y/N] "
            )
        except EOFError:
            answer = ""
        if answer.strip().casefold() not in {"y", "yes"}:
            print("Cancelled; backup was not deleted.")
            return 0

    store["entries"] = [candidate for candidate in store["entries"] if candidate is not entry]
    save_backup_store(backup_path, store)
    print(f"Deleted backup {backup_id} for App ID {entry['app_id']} ({branch}).")
    return 0


def _run_install_steamcmd(repair: bool = False) -> int:
    action = "checking or repairing" if repair else "checking or installing"
    print(f"{action.capitalize()} SteamCMD for the current user...")
    executable, installed = install_steamcmd(repair=repair)
    if installed:
        status = "installed or repaired" if repair else "installed"
        print(f"SteamCMD {status}: {executable}")
        print("Its first run may download SteamCMD updates before fetching app information.")
    else:
        print(f"SteamCMD is already installed for this user: {executable}")
    return 0


def _run_gui(args: argparse.Namespace) -> int:
    try:
        from .gui import launch_gui
    except ModuleNotFoundError as error:
        if error.name != "PySide6":
            raise
        raise SwitcherError(
            "GUI support requires the optional PySide6 dependency. "
            "Install SGS with 'uv tool install \".[gui]'."
        ) from error
    return launch_gui(
        config=args.config,
        app_id=args.app_id,
        steamapps=args.steamapps,
        manifest=args.manifest,
        steamcmd=args.steamcmd,
        guard=args.guard,
        refresh=args.refresh,
        cache=args.cache,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line application and return its process status."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command not in {"defaults", "steamcmd"} and args.app_id is None:
            args.app_id = load_root_state(args.config)["default_app_id"]
        if args.manifest is not None and args.steamapps is not None:
            raise SwitcherError("Use either --manifest or --steamapps, not both.")
        if args.command == "branches":
            return _run_branches(args)
        if args.command == "status":
            return _run_status(args)
        if args.command == "settings":
            return _run_settings(args)
        if args.command == "defaults":
            return _run_defaults(args)
        if args.command == "switch":
            return _run_switch(args)
        if args.command == "shortcuts":
            return _run_shortcuts(args)
        if args.command == "gui":
            return _run_gui(args)
        if args.command == "backup" and args.backup_command == "list":
            return _run_backups(args)
        if args.command == "backup" and args.backup_command == "restore":
            return _run_restore(args)
        if args.command == "backup" and args.backup_command == "delete":
            return _run_delete(args)
        return _run_install_steamcmd(args.steamcmd_command == "repair")
    except SteamCMDNotFoundError as error:
        print(f"Warning: {error}", file=sys.stderr)
        return 2
    except SwitcherError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
