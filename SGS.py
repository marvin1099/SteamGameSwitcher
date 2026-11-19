#!/usr/bin/env python3
"""Compatibility launcher for users of the original single-file SGS script."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from steam_game_switcher.cli import main as cli_main  # noqa: E402


def main() -> int:
    arguments = sys.argv[1:]
    app_options: list[str] = []
    if len(arguments) >= 2 and arguments[0] == "id":
        app_options = ["--app-id", arguments[1]]
        arguments = arguments[2:]

    if not arguments or arguments[0] not in {"branches", "status", "switch", "-h", "--help"}:
        arguments = ["switch", *arguments]
    return cli_main([*app_options, *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
