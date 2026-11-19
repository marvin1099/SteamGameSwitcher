import io
import os
import tarfile
import zipfile

import pytest

from steam_game_switcher.errors import SteamCMDInstallError
from steam_game_switcher.steamcmd_install import VALVE_DOWNLOADS, install_steamcmd


def _tar_archive(files: dict[str, bytes]) -> bytes:
    archive_data = io.BytesIO()
    with tarfile.open(fileobj=archive_data, mode="w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.mode = 0o644
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return archive_data.getvalue()


def test_install_steamcmd_downloads_and_installs_for_current_user(tmp_path):
    archive_data = _tar_archive({"steamcmd.sh": b"#!/bin/sh\nexit 0\n"})
    install_directory = tmp_path / "data" / "steamcmd"
    downloaded_urls = []

    def fake_download(url, destination):
        downloaded_urls.append(url)
        destination.write_bytes(archive_data)

    executable, installed = install_steamcmd(install_directory, "Linux", fake_download)

    assert executable == install_directory / "steamcmd.sh"
    assert installed is True
    assert os.access(executable, os.X_OK)
    assert downloaded_urls == [VALVE_DOWNLOADS["Linux"][0]]

    existing_executable, installed_again = install_steamcmd(
        install_directory, "Linux", lambda *_args: pytest.fail("should not redownload")
    )
    assert existing_executable == executable
    assert installed_again is False


def test_install_steamcmd_supports_valve_windows_zip(tmp_path):
    archive_data = io.BytesIO()
    with zipfile.ZipFile(archive_data, mode="w") as archive:
        archive.writestr("steamcmd.exe", b"not a real executable")

    def fake_download(url, destination):
        assert url == VALVE_DOWNLOADS["Windows"][0]
        destination.write_bytes(archive_data.getvalue())

    executable, installed = install_steamcmd(tmp_path / "steamcmd", "Windows", fake_download)

    assert executable.is_file()
    assert installed is True


def test_install_steamcmd_rejects_archive_path_traversal(tmp_path):
    archive_data = _tar_archive({"../escaped.txt": b"nope", "steamcmd.sh": b"#!/bin/sh\n"})

    def fake_download(_url, destination):
        destination.write_bytes(archive_data)

    with pytest.raises(SteamCMDInstallError, match="unsafe file path"):
        install_steamcmd(tmp_path / "data" / "steamcmd", "Linux", fake_download)

    assert not (tmp_path / "escaped.txt").exists()
