# Steam Game Switcher

Steam Game Switcher (SGS) is a command-line tool for switching a game's selected
Steam branch by safely updating its local `appmanifest_<app-id>.acf`.

- Main repository: <https://codeberg.org/marvin1099/SteamGameSwitcher>
- GitHub mirror: <https://github.com/marvin1099/SteamGameSwitcher>

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- The game installed in a Steam library on this computer

SteamCMD is used to retrieve public branch names; it does not download or install
game files. Steam performs those updates after it notices the changed manifest.
SGS uses SteamCMD from `PATH` or its per-user install directory. If it is missing,
branch commands show a warning and can use cached branch data when available.

## Install for development

```sh
git clone https://github.com/marvin1099/SteamGameSwitcher.git
cd SteamGameSwitcher
uv sync
```

Run the CLI from the project checkout with `uv run`:

```sh
uv run sgs --help
```

To install a standalone command in the active environment, use `uv tool install .`
from the project directory.

To download SteamCMD directly from Valve and install it for the current user (no
administrator access required), run:

```sh
uv run sgs install-steamcmd
```

The installer supports Valve's Linux, Windows, and macOS archives, installs under
the user's application data directory, and does not launch SteamCMD during
installation. The first branch lookup may let SteamCMD update itself.
If a managed install is incomplete or needs replacing, run:

```sh
uv run sgs install-steamcmd --repair
```

It downloads and extracts the replacement before swapping it in, and attempts to
restore the previous copy if activation fails.

On Linux, SteamCMD may also require 32-bit compatibility/runtime libraries from
your distribution. Package names vary; SGS only installs SteamCMD files and does
not install system libraries or request administrator access. If SteamCMD cannot
start, install the runtime dependencies recommended by your distribution.

## Usage

The default App ID is `526870` (Satisfactory). Steam libraries and the app
manifest are detected automatically when possible; pass a path explicitly when
the game is installed somewhere unusual.

```sh
# Show public branches; public is displayed by name
uv run sgs branches

# See the branch currently recorded in the appmanifest
uv run sgs status

# Cycle forward, or select a branch by name or one-based index
uv run sgs switch
uv run sgs switch previous
uv run sgs switch experimental
uv run sgs switch 2

# Use another game or a non-default Steam library
uv run sgs --app-id 400 --steamapps "/path/to/Steam/steamapps" branches
uv run sgs --app-id 400 --steamapps "/path/to/Steam/steamapps" switch public

# Preview a switch without changing the manifest or saved configuration
uv run sgs switch experimental --dry-run

# Generate desktop launchers for selected branches (-1 is the last branch)
uv run sgs shortcuts -1 experimental

# Browse saved manifest backups and restore one by ID
uv run sgs backups
uv run sgs restore 0123456789abcdef  # replace with an ID shown by backups

# Install SteamCMD for this user if SGS warns that it is missing
uv run sgs install-steamcmd

# Replace or repair the managed SteamCMD install
uv run sgs install-steamcmd --repair
```

Target names are case-sensitive and must match a public branch. Numeric indices
are one-based; negative indices count from the end (`-1` is the last branch).
`0`, `next`, and no target select the next branch; `-`, `prev`, and `previous`
select the previous branch. The public branch can be selected with `public`.

`sgs shortcuts` creates one launcher per selected branch in the user's Desktop
directory by default. Linux gets `.desktop` files, Windows gets hidden `.vbs`
launchers, and macOS gets executable `.command` files. Use `--output DIR` to
choose another folder and `--force` to replace existing generated files.

Use `--refresh` before `branches`, `switch`, or `shortcuts` to refresh SteamCMD's
branch data instead of using the 24-hour cache. If SteamCMD is unavailable during
a refresh, SGS uses an existing cached branch list and prints a warning.

## Per-game settings and install directories

Separate install directories are enabled by default for each App ID. Branches
get names such as `Satisfactory` and `Satisfactory-experimental`, allowing the
installed files for each branch to remain separate. To use a shared folder for
one game instead:

```sh
uv run sgs switch experimental --shared-folder
```

Use `--separate-folders` to re-enable separate directories for that game. The
setting is saved per App ID. Custom folder names can be set in the JSON config
under that game's `install_dirs` mapping. SGS changes the install directory in
the appmanifest; Steam manages the actual download and installation. Folder names
must be portable single components. SGS checks the destination filesystem's
component-length limit, shortens generated names that exceed it, and rejects
overlong custom names. On common Linux filesystems, this limit is 255 bytes;
the exact value depends on the destination filesystem.

Before switching, SGS saves the previous appmanifest data in `backups.json` next
to the config file. Identical backups for the same game and manifest path are
deduplicated. Manifests are written atomically, and Steam is never terminated.
For best results, exit Steam before switching so it cannot overwrite a manifest
while SGS is editing it.

## Configuration and recovery

The JSON state file is stored in the operating system's user configuration
directory (via `platformdirs`). Override its location with `--config`. State is
kept per App ID and contains the public-branch cache, the separate-directory
setting, and optional install-directory names. Backups store the parsed ACF data
as JSON and can be listed with `sgs backups` and restored with `sgs restore ID`.
Restoring also backs up the current manifest first, unless that exact state is
already present in the backup index. Pass `--manifest` to restore to a different
path than the one recorded in the backup, placing the option before the command:

```sh
uv run sgs --manifest "/path/to/appmanifest_526870.acf" restore 0123456789abcdef
```

Saved branch profiles from an earlier SGS config are moved into `backups.json`
when the next non-dry-run switch occurs; their config entries are removed only
after the backup file is saved. Existing per-game directory choices are preserved.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The project is licensed under the GNU Affero General Public License v3 or later;
see [LICENSE](LICENSE).
