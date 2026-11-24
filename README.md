# Steam Game Switcher

SGS switches Steam branches by editing a game's local appmanifest. Steam handles
downloads and updates; SGS does not move game files.

## Install

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and a game installed in
a Steam library.

```sh
git clone https://github.com/marvin1099/SteamGameSwitcher.git
cd SteamGameSwitcher
uv tool install .
```

Run `sgs` after installation. If it is not found, add uv's tool directory to your
`PATH`. Install SteamCMD with `sgs steamcmd install`; replace it with
`sgs steamcmd repair`. On Linux, SteamCMD may need 32-bit runtime packages.

### Optional graphical interface

PySide6 is not required by the CLI. Install the GUI extra and launch it with:

```sh
uv tool install ".[gui]"
sgs gui
```

If SGS is already installed without the GUI, reinstall the tool with the extra:

```sh
uv tool install --force ".[gui]"
```

The GUI includes branch status and switching, per-game settings and new-game
defaults, manifest backup restore/deletion, branch shortcuts, and SteamCMD
installation. Actions that change a branch, restore a backup, or delete a backup
ask for confirmation. It uses the same config, manifest, SteamCMD, and guard
options as the CLI; for example, `sgs --app-id 400 --guard gui`.
On Linux, launching the GUI also registers a matching SVG app-menu launcher
under the user's applications directory so the taskbar can use the same icon.

## Quick start

The default game is Satisfactory (App ID `526870`). Change the saved default with
`sgs defaults --app-id 400`; pass `--app-id` before a command to override it once.
SGS detects the library and manifest automatically when possible.

```sh
sgs branches
sgs status
sgs switch experimental
```

### Choose a branch

```sh
sgs switch                 # next branch
sgs switch previous
sgs switch 2                # second branch in the list
sgs switch experimental --dry-run
```

Names are case-sensitive and must appear in `sgs branches`. Numbers start at 1;
`-1` selects the last branch. Use `public` for the public branch.

If you change branches in Steam after SGS has managed the game, run
`sgs switch <branch>` to reconcile the branch's install folder and manifest
settings, even if Steam already shows that branch as active.

For another game, pass `--app-id`. To select a Steam library manually, pass its
`steamapps` directory:

```sh
sgs --app-id 400 branches
sgs --app-id 400 --steamapps "/path/to/Steam/steamapps" switch public
```

### Install folders

Separate folders are enabled by default. Set or replace a known branch's folder:

```sh
sgs switch experimental --install-dir SatisfactoryEX
```

The branch must appear in `sgs branches`. The folder name must be a single
component. This changes the appmanifest; it does not move files. Use
`sgs settings --shared-folder` to use one folder for all branches, or
`sgs settings --separate-folders` to re-enable separate folders without
switching branches.

### Steam after a switch

These preferences are saved per App ID and are off by default:

```sh
sgs settings --restart-steam-on-switch --launch-game-after-switch
sgs settings --launch-game-when-unchanged
sgs settings --no-restart-steam-on-switch --no-launch-game-after-switch
sgs switch experimental
sgs status
```

`sgs settings` only reads or saves preferences; it does not inspect or edit a
manifest, switch branches, restart Steam, or launch the game. Steam restart and
`--launch-game-after-switch` apply only when changing branches.
`--launch-game-when-unchanged` separately allows launching when the requested
branch is already active; it is off by default. When restart is enabled, Steam is
closed gracefully before branch changes and restarted afterward. If it will not
close, SGS aborts; it never force-terminates Steam. By default, SGS warns if Steam
is running or its status cannot be checked, then proceeds; the user is responsible
for Steam's state. Pass `--guard` before a command to refuse manifest edits in
those cases when SGS is not automatically restarting Steam; `--no-guard`
explicitly selects the warning-only behavior. Game launch uses
`steam://rungameid/<AppID>`.

Use `sgs defaults` to view or change defaults for new game entries:

```sh
sgs defaults --restart-steam --launch-game --separate-folders
sgs defaults --launch-game-when-unchanged
```

Use `--no-restart-steam`, `--no-launch-game`, or
`--no-launch-game-when-unchanged` to turn defaults off. Defaults affect new game
entries only; existing games keep their saved settings.

### Cache and shortcuts

Branch data normally refreshes every 24 hours. `--refresh` requires a successful
fresh fetch and fails rather than using stale data. `--cache` uses expired cache
data if available and fetches only when no usable cache exists. These options
cannot be combined.

```sh
sgs --refresh branches
sgs --cache switch experimental
```

Create branch launchers with `sgs shortcuts experimental public`. By default,
they go to the app launcher folder: Linux Applications menu, Windows Start Menu,
or macOS `~/Applications`. SGS prints the destination path. Use `--output DIR`
to choose another folder or `--force` to replace existing launchers.

## Backups

List, restore, or delete backups:

```sh
sgs backup list
sgs backup restore 1                       # number from the list
sgs backup restore 0123456789abcdef        # stable backup ID
sgs backup delete 1                        # asks before deleting
sgs backup delete --global-numbering 3 --yes
```

By default, the list is filtered to the selected App ID. Numbers are generated
from the current newest-first list, not saved, so they can change as backups
change. Filter to another game or use global numbering with:

```sh
sgs backup list --app-id 400
sgs backup restore --app-id 400 1
sgs backup list --all
sgs backup restore --global-numbering 2
sgs backup delete --global-numbering 3 --yes
```

When needed, restore saves the current manifest before replacing it. Delete
removes only the backup record, not the live manifest. To restore another
manifest, put `--manifest PATH` before the `backup` command.
Branch-changing restores follow the game's saved restart and launch preferences.
With the default warning-only behavior, SGS proceeds if Steam may be running;
pass `--guard` to refuse if SGS is not automatically restarting Steam for that
branch change.

## Config and safety

- Config and `backups.json` are stored in the user config directory; use
  `--config PATH` to choose another location.
- By default, SGS warns but proceeds if Steam is running or its status cannot be
  checked; the user is responsible for Steam's state. Use `--guard` to refuse the
  manifest edit when SGS is not automatically restarting Steam. The saved restart
  preference asks Steam to close and relaunch on branch changes; if Steam will not
  close, SGS aborts and never force-terminates it.
- Older saved branch profiles are moved to `backups.json` on the next real
  (non-dry-run) switch.

## Development

From the project directory, install development dependencies with `uv sync`.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Licensed under the GNU Affero General Public License v3 or later; see [LICENSE](LICENSE).
