import importlib
import os
import signal
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="module")
def gui_types():
    pytest.importorskip("PySide6")
    widgets = importlib.import_module("PySide6.QtWidgets")
    qtgui = importlib.import_module("PySide6.QtGui")
    qttest = importlib.import_module("PySide6.QtTest")
    gui = importlib.import_module("steam_game_switcher.gui")
    return (
        widgets.QApplication,
        gui.SGSWindow,
        gui.CommandResult,
        gui.QMessageBox,
        widgets.QGroupBox,
        qtgui.QColor,
        qtgui.QPalette,
        widgets.QFrame,
        qttest.QTest,
        qttest.QSignalSpy,
    )


@pytest.fixture(scope="module")
def qapp(gui_types):
    QApplication = gui_types[0]
    return QApplication.instance() or QApplication([])


def _wait_for_condition(QSignalSpy, signal, condition, timeout_ms=1000):
    spy = QSignalSpy(signal)
    deadline = monotonic() + timeout_ms / 1000
    while not condition():
        remaining_ms = int((deadline - monotonic()) * 1000)
        if remaining_ms <= 0 or not spy.wait(remaining_ms):
            return condition()
    return True


@pytest.fixture
def gui_window(tmp_path, monkeypatch, qapp, gui_types):
    SGSWindow = gui_types[1]
    monkeypatch.setattr(SGSWindow, "_run_commands", lambda self, _commands, _completion=None: None)
    window = SGSWindow(config=tmp_path / "config.json", app_id=7654321)
    yield window
    window.close()
    window.deleteLater()
    qapp.sendPostedEvents(None, 0)
    qapp.processEvents()


def test_locations_and_safety_starts_expanded_and_activity_grows_when_collapsed(
    gui_window, gui_types, qapp
):
    QGroupBox = gui_types[4]
    assert isinstance(gui_window.locations_content, QGroupBox)
    assert not gui_window.locations_content.isHidden()

    gui_window.resize(1050, 800)
    gui_window.show()
    qapp.processEvents()
    expanded_activity_height = gui_window.activity.height()

    gui_window.locations_toggle.click()
    qapp.processEvents()
    assert gui_window.locations_content.isHidden()
    assert gui_window.activity.height() > expanded_activity_height

    gui_window.locations_toggle.click()
    qapp.processEvents()
    assert not gui_window.locations_content.isHidden()


def test_dry_run_output_remains_visible_without_refreshing_status(
    gui_window, monkeypatch, gui_types
):
    CommandResult = gui_types[2]
    gui_window.branch_choice.addItem("beta", "beta")
    gui_window._loaded_branches = ["beta"]
    gui_window.dry_run_input.setChecked(True)
    captured_commands = []

    def run_stub(commands, completion=None):
        captured_commands.extend(commands)
        if completion is not None:
            completion([CommandResult(commands[0], 0, "Would switch to beta.\n", "")])

    monkeypatch.setattr(gui_window, "_run_commands", run_stub)

    gui_window.switch_branch()

    assert captured_commands[0][-3:] == ["switch", "beta", "--dry-run"]
    assert gui_window.status_details.toPlainText() == "Would switch to beta."
    assert gui_window.game_summary.text() == (
        "Dry-run preview for beta complete — no files were changed."
    )


def test_switch_button_label_and_switch_without_confirmation(gui_window, monkeypatch, gui_types):
    QMessageBox = gui_types[3]
    captured_commands = []

    def reject_confirmation(*_args, **_kwargs):
        pytest.fail("Switch branch must not ask for confirmation.")

    monkeypatch.setattr(QMessageBox, "question", reject_confirmation)
    monkeypatch.setattr(
        gui_window,
        "_run_commands",
        lambda commands, _completion=None: captured_commands.extend(commands),
    )
    gui_window.branch_choice.addItem("beta", "beta")

    assert gui_window.switch_button.text() == "Switch branch (instant)"
    gui_window.switch_branch()

    assert captured_commands[0][-2:] == ["switch", "beta"]

    gui_window.dry_run_input.setChecked(True)
    assert gui_window.switch_button.text() == "Preview branch switch"
    gui_window.dry_run_input.setChecked(False)
    assert gui_window.switch_button.text() == "Switch branch (instant)"


def test_activity_log_outlines_commands(gui_window, gui_types):
    activity = gui_window.activity
    activity.append_command("$ sgs first")
    activity.append_text("First command output")
    activity.append_command("$ sgs second")

    QFrame = gui_types[7]
    assert "#808080" in activity.findChild(QFrame, "sgsActivityCommandHistory").styleSheet()
    expected_latest = activity._current_outline_color()
    assert expected_latest in activity.findChild(QFrame, "sgsActivityCommandLatest").styleSheet()

    QColor = gui_types[5]
    QPalette = gui_types[6]
    palette = activity.palette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#111111"))
    activity.setPalette(palette)
    assert "#000000" in activity.findChild(QFrame, "sgsActivityCommandLatest").styleSheet()


def test_activity_command_rows_stay_compact(gui_window, gui_types):
    QTest = gui_types[8]
    gui_window.resize(1050, 600)
    activity = gui_window.activity
    activity.append_command(
        "$ sgs --config /tmp/opencode/sgs-activity-layout-check/config.json "
        "--app-id 7654321 --manifest "
        "/tmp/opencode/sgs-activity-layout-check/appmanifest_7654321.acf --no-guard "
        "--cache switch experimental"
    )
    activity.append_text("Switched branch to beta.")
    gui_window.show()
    QTest.qWait(50)

    latest_command = activity.findChild(gui_types[7], "sgsActivityCommandLatest")
    latest_output = activity._log_layout.itemAt(activity._log_layout.count() - 1).widget()
    assert latest_command is not None
    assert latest_output is not None
    assert latest_command.height() <= 50
    assert latest_output.height() <= 40


def test_activity_multiline_output_keeps_its_text_height(gui_window, gui_types):
    QTest = gui_types[8]
    gui_window.resize(1050, 600)
    activity = gui_window.activity
    activity.append_text("First result line\nSecond result line\nThird result line")
    gui_window.show()
    QTest.qWait(50)

    latest_output = activity._log_layout.itemAt(activity._log_layout.count() - 1).widget()
    assert latest_output is not None
    assert latest_output.height() >= 40
    assert latest_output.height() <= 60


def test_activity_log_scrolls_to_new_entries(gui_window, gui_types, qapp):
    QSignalSpy = gui_types[9]
    gui_window.resize(1050, 600)
    gui_window.show()
    qapp.processEvents()

    activity = gui_window.activity
    for index in range(40):
        activity.append_text(f"Activity entry {index}")

    scroll_bar = activity.verticalScrollBar()
    assert _wait_for_condition(
        QSignalSpy,
        scroll_bar.valueChanged,
        lambda: scroll_bar.maximum() > 0 and scroll_bar.value() == scroll_bar.maximum(),
    )
    assert scroll_bar.maximum() > 0
    assert scroll_bar.value() == scroll_bar.maximum()
    latest_entry = activity._log_layout.itemAt(activity._log_layout.count() - 1).widget()
    assert latest_entry is not None
    latest_bottom = latest_entry.mapTo(activity.viewport(), latest_entry.rect().bottomRight()).y()
    assert 0 <= latest_bottom <= activity.viewport().height()
    assert activity.widget().height() - latest_entry.geometry().bottom() <= 10

    gui_window.resize(1050, 700)
    qapp.processEvents()
    assert _wait_for_condition(
        QSignalSpy,
        scroll_bar.valueChanged,
        lambda: scroll_bar.value() == scroll_bar.maximum(),
    )


def test_ctrl_c_quits_gui_event_loop(tmp_path, monkeypatch, qapp):
    QTimer = importlib.import_module("PySide6.QtCore").QTimer
    gui = importlib.import_module("steam_game_switcher.gui")
    previous_handler = signal.getsignal(signal.SIGINT)

    monkeypatch.setattr(gui, "install_application_desktop_entry", lambda: None)
    monkeypatch.setattr(gui.SGSWindow, "_run_commands", lambda *_args, **_kwargs: None)
    QTimer.singleShot(100, lambda: os.kill(os.getpid(), signal.SIGINT))

    assert gui.launch_gui(config=tmp_path / "config.json", app_id=7654321) == 128 + signal.SIGINT
    assert signal.getsignal(signal.SIGINT) is previous_handler
