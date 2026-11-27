"""Package a native PyInstaller binary with the project license and README."""

from __future__ import annotations

import argparse
import tomllib
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform",
        required=True,
        choices=("linux-x86_64", "windows-x86_64", "macos-arm64"),
    )
    args = parser.parse_args()

    with Path("pyproject.toml").open("rb") as project_file:
        version = tomllib.load(project_file)["project"]["version"]

    executable_name = "sgs.exe" if args.platform == "windows-x86_64" else "sgs"
    executable = Path("dist") / executable_name
    if not executable.is_file():
        parser.error(f"PyInstaller binary not found at {executable}")

    output_directory = Path("release-output")
    output_directory.mkdir(parents=True, exist_ok=True)
    archive_path = output_directory / (f"steam-game-switcher-{version}-{args.platform}.zip")

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, executable_name)
        archive.write("README.md", "README.md")
        archive.write("LICENSE", "LICENSE")

    print(f"Created {archive_path}")


if __name__ == "__main__":
    main()
