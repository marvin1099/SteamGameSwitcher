"""Application exceptions used to report actionable CLI errors."""


class SwitcherError(Exception):
    """An expected error that can be shown directly to the CLI user."""


class SteamCMDError(SwitcherError):
    """SteamCMD is missing, failed, or returned unreadable app information."""


class SteamCMDNotFoundError(SteamCMDError):
    """SteamCMD is unavailable and no cached branch list can be used."""


class SteamCMDInstallError(SwitcherError):
    """SteamCMD could not be downloaded or installed for the current user."""
