"""Per-user SteamCMD discovery and installation from Valve's official CDN."""

from __future__ import annotations

import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.error import URLError
from urllib.request import Request, urlopen

from platformdirs import user_data_path

from .errors import SteamCMDInstallError

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
VALVE_DOWNLOADS = {
    "Linux": ("https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz", "tar"),
    "Windows": ("https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip", "zip"),
    "Darwin": ("https://steamcdn-a.akamaihd.net/client/installer/steamcmd_osx.tar.gz", "tar"),
}


def managed_steamcmd_directory() -> Path:
    """Return the user-local directory used by SGS for SteamCMD."""
    return Path(user_data_path("steam-game-switcher", appauthor=False)) / "steamcmd"


def _binary_name(system_name: str) -> str:
    if system_name == "Windows":
        return "steamcmd.exe"
    if system_name in {"Linux", "Darwin"}:
        return "steamcmd.sh"
    raise SteamCMDInstallError(
        f"Automatic SteamCMD installation is not supported on {system_name}."
    )


def find_steamcmd(executable: str | None = None) -> str | None:
    """Find an explicit, user-managed, or PATH SteamCMD executable."""
    if executable:
        candidate = Path(executable).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        return shutil.which(executable)

    try:
        managed = managed_steamcmd_directory() / _binary_name(platform_system())
    except SteamCMDInstallError:
        managed = None
    if managed is not None and managed.is_file():
        return str(managed.resolve())

    candidates = (
        ("steamcmd.exe", "steamcmd", "steamcmd.sh")
        if os.name == "nt"
        else (
            "steamcmd",
            "steamcmd.sh",
        )
    )
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def platform_system() -> str:
    """Return the standard OS name, isolated to make installation testable."""
    return platform.system()


def _download_archive(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "SteamGameSwitcher/1.0"})
    total_bytes = 0
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise SteamCMDInstallError("Valve's SteamCMD archive is unexpectedly large.")
            while chunk := response.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_ARCHIVE_BYTES:
                    raise SteamCMDInstallError("Valve's SteamCMD archive exceeded the size limit.")
                output.write(chunk)
    except SteamCMDInstallError:
        raise
    except (OSError, URLError, ValueError) as error:
        raise SteamCMDInstallError(f"Could not download SteamCMD from Valve: {error}") from error


def _archive_path(root: Path, member_name: str) -> Path:
    posix_path = PurePosixPath(member_name)
    windows_path = PureWindowsPath(member_name)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in posix_path.parts
    ):
        raise SteamCMDInstallError("SteamCMD archive contains an unsafe file path.")
    relative_parts = tuple(part for part in posix_path.parts if part not in {"", "."})
    destination = root.joinpath(*relative_parts)
    try:
        destination.resolve(strict=False).relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError) as error:
        raise SteamCMDInstallError(
            "SteamCMD archive contains a path outside its install folder."
        ) from error
    return destination


def _extract_tar_securely(archive_path: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            total_size = sum(member.size for member in members if member.isfile())
            if total_size > MAX_EXTRACTED_BYTES:
                raise SteamCMDInstallError("SteamCMD archive expands beyond the size limit.")
            for member in members:
                target = _archive_path(destination, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(member.mode & 0o777)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise SteamCMDInstallError("SteamCMD archive contains an unreadable file.")
                    with source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(member.mode & 0o777)
                elif member.issym():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    link_name = PurePosixPath(member.linkname)
                    if link_name.is_absolute() or ".." in link_name.parts:
                        raise SteamCMDInstallError(
                            "SteamCMD archive contains an unsafe symbolic link."
                        )
                    try:
                        (target.parent / member.linkname).resolve(strict=False).relative_to(
                            destination.resolve()
                        )
                    except (OSError, RuntimeError, ValueError) as error:
                        raise SteamCMDInstallError(
                            "SteamCMD archive contains a symbolic link outside its install folder."
                        ) from error
                    os.symlink(member.linkname, target)
                else:
                    raise SteamCMDInstallError(
                        "SteamCMD archive contains an unsupported file type."
                    )
    except (OSError, tarfile.TarError) as error:
        raise SteamCMDInstallError(f"Could not extract SteamCMD archive: {error}") from error


def _extract_zip_securely(archive_path: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if sum(member.file_size for member in archive.infolist()) > MAX_EXTRACTED_BYTES:
                raise SteamCMDInstallError("SteamCMD archive expands beyond the size limit.")
            for member in archive.infolist():
                target = _archive_path(destination, member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise SteamCMDInstallError(
                        "SteamCMD ZIP contains an unsupported symbolic link."
                    )
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise SteamCMDInstallError(f"Could not extract SteamCMD archive: {error}") from error


def install_steamcmd(
    install_directory: Path | None = None,
    system_name: str | None = None,
    downloader: Callable[[str, Path], None] = _download_archive,
) -> tuple[Path, bool]:
    """Download and install SteamCMD for the current user without elevation."""
    system = system_name or platform_system()
    try:
        url, archive_format = VALVE_DOWNLOADS[system]
        binary_name = _binary_name(system)
    except KeyError as error:
        raise SteamCMDInstallError(
            f"Automatic SteamCMD installation is not supported on {system}."
        ) from error

    install_path = install_directory or managed_steamcmd_directory()
    install_path = install_path.expanduser().resolve()
    binary_path = install_path / binary_name
    if binary_path.is_file():
        return binary_path, False
    if install_path.exists():
        raise SteamCMDInstallError(
            f"Install directory already exists but has no {binary_name}: {install_path}"
        )

    try:
        install_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".steamcmd-install-", dir=install_path.parent
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            archive_name = "steamcmd.zip" if archive_format == "zip" else "steamcmd.tar.gz"
            archive_path = temporary_path / archive_name
            extracted_path = temporary_path / "extracted"
            extracted_path.mkdir()
            downloader(url, archive_path)
            if archive_format == "zip":
                _extract_zip_securely(archive_path, extracted_path)
            else:
                _extract_tar_securely(archive_path, extracted_path)

            staged_binary = extracted_path / binary_name
            if not staged_binary.is_file():
                raise SteamCMDInstallError(
                    f"Valve's SteamCMD archive did not contain the expected {binary_name}."
                )
            for executable_name in ("steamcmd.sh", "steamcmd", "linux32/steamcmd"):
                executable_path = extracted_path / executable_name
                if executable_path.is_file() and system != "Windows":
                    executable_path.chmod(executable_path.stat().st_mode | 0o111)
            os.replace(extracted_path, install_path)
    except SteamCMDInstallError:
        raise
    except OSError as error:
        raise SteamCMDInstallError(
            f"Could not install SteamCMD to '{install_path}': {error}"
        ) from error

    return binary_path, True
