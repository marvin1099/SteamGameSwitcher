"""Entry point used to freeze the package into a standalone executable."""

from steam_game_switcher.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
