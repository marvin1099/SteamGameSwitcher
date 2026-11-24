import stat
import xml.etree.ElementTree as ET

from steam_game_switcher import desktop_integration


def test_application_icon_is_valid_svg():
    icon_path = desktop_integration.application_icon_path()

    root = ET.parse(icon_path).getroot()

    assert root.tag == "{http://www.w3.org/2000/svg}svg"


def test_render_application_desktop_entry_quotes_exec_arguments(tmp_path):
    executable = tmp_path / "SGS tool" / "sgs"
    icon = tmp_path / "icons" / "sgs icon.svg"

    contents = desktop_integration.render_application_desktop_entry(
        [str(executable), "gui"],
        icon_path=icon,
    )

    assert f'Exec="{executable}" "gui"' in contents
    assert f"Icon={icon}" in contents
    assert "StartupWMClass=steam-game-switcher" in contents
    assert "Terminal=false" in contents


def test_install_application_desktop_entry_creates_linux_app_menu_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setattr(desktop_integration.sys, "platform", "linux")
    monkeypatch.setattr(desktop_integration.shutil, "which", lambda _name: "/tools/sgs")

    entry = desktop_integration.install_application_desktop_entry()

    assert entry == tmp_path / "xdg-data" / "applications" / "steam-game-switcher.desktop"
    contents = entry.read_text(encoding="utf-8")
    assert 'Exec="/tools/sgs" "gui"' in contents
    assert f"Icon={desktop_integration.application_icon_path().resolve()}" in contents
    assert stat.S_IMODE(entry.stat().st_mode) & 0o111


def test_install_does_not_replace_an_unmanaged_launcher(tmp_path, monkeypatch):
    data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setattr(desktop_integration.sys, "platform", "linux")
    monkeypatch.setattr(desktop_integration.shutil, "which", lambda _name: "/tools/sgs")
    entry = data_home / "applications" / "steam-game-switcher.desktop"
    entry.parent.mkdir(parents=True)
    entry.write_text("[Desktop Entry]\nName=My custom SGS launcher\n", encoding="utf-8")

    result = desktop_integration.install_application_desktop_entry()

    assert result is None
    assert entry.read_text(encoding="utf-8") == ("[Desktop Entry]\nName=My custom SGS launcher\n")
