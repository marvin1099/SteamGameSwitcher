# Steam Game Switcher

Steam Game Switcher (SGS) is a small command-line tool for switching a game's
selected Steam branch by safely updating its local `appmanifest_<app-id>.acf`.
It is based on the branch switching, per-branch manifest profiles, custom App IDs,
and optional separate install-directory ideas in the earlier SGS prototypes.

- Main repository: <https://codeberg.org/marvin1099/SteamGameSwitcher>
- GitHub mirror: <https://github.com/marvin1099/SteamGameSwitcher>

## Requirements

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- SteamCMD available on `PATH` (or pass its location with `--steamcmd`)
- The game installed in a Steam library on this computer

SteamCMD is used to retrieve public branch names; it does not download or install
game files. Steam performs those updates after it notices the changed manifest.

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
```

Target names are case-sensitive and must match a public branch. Numeric indices
are one-based; negative indices count from the end (`-1` is the last branch).
`0`, `next`, and no target select the next branch; `-`, `prev`, and `previous`
select the previous branch. The public branch can be selected with `public`.

Use `--refresh` before `branches` or `switch` to refresh SteamCMD's branch data
instead of using the 24-hour cache. If SteamCMD is unavailable during a refresh,
SGS uses an existing cached branch list and prints a warning.

## Separate install directories

By default, branch switches keep the current `installdir`, matching Steam's
usual shared-install behavior. To opt into different manifest install-directory
names per branch:

```sh
uv run sgs switch experimental --separate-folders
```

SGS derives safe folder names such as `Satisfactory-experimental`; custom names
can be set in the JSON config under the selected game's `install_dirs` mapping.
`--shared-folder` switches back to the current shared folder. This feature only
changes the directory name recorded in the appmanifest: it does not copy, move,
or duplicate game files. Steam manages the actual download and installation.

Before switching, SGS saves a timestamped backup beside the appmanifest and keeps
a local manifest profile for each branch. It writes manifests atomically and
never terminates Steam processes. For best results, exit Steam before switching
so Steam cannot overwrite a manifest while it is being edited.

## Configuration and compatibility

The JSON state file is stored in the operating system's user configuration
directory (via `platformdirs`). Override its location with `--config`. State is
kept per App ID and contains the public-branch cache, branch manifest profiles,
and optional install-directory names. Old script-specific `.txt` VDF configs
are not imported automatically; existing Steam appmanifests are still used.

The original script name remains available as a compatibility launcher:

```sh
python SGS.py 2
python SGS.py id 400 experimental
```

New use should prefer the installed `sgs` command and its `branches`, `status`,
and `switch` subcommands.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The project is licensed under the GNU Affero General Public License v3 or later;
see [LICENSE](LICENSE).
