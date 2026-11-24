"""Optional PySide6 graphical interface for Steam Game Switcher."""

from __future__ import annotations

import re
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .backups import backup_store_path, load_backup_store
from .cli import _ordered_backups
from .desktop_integration import (
    DESKTOP_FILE_NAME,
    application_icon_path,
    install_application_desktop_entry,
)
from .errors import SwitcherError
from .shortcuts import default_shortcut_directory
from .state import load_state
from .switcher import branch_label


@dataclass
class CommandResult:
    """The captured result of one CLI command launched by the GUI."""

    arguments: list[str]
    return_code: int
    stdout: str
    stderr: str


class _ActivityLog(QScrollArea):
    """Scrollable activity log with bordered command rows."""

    _HISTORY_BORDER = "#808080"
    _MAX_ENTRIES = 3000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(115)
        self._scroll_pending = False

        contents = QWidget()
        self._log_layout = QVBoxLayout(contents)
        self._log_layout.setContentsMargins(2, 2, 2, 2)
        self._log_layout.setSpacing(3)
        self.setWidget(contents)
        self._sync_content_geometry()

    def append_command(self, text: str) -> None:
        previous = self.findChild(QFrame, "sgsActivityCommandLatest")
        if previous is not None:
            previous.setObjectName("sgsActivityCommandHistory")
            self._style_command_frame(previous, self._HISTORY_BORDER)

        frame = QFrame()
        frame.setObjectName("sgsActivityCommandLatest")
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        row = QHBoxLayout(frame)
        row.setContentsMargins(5, 3, 5, 3)
        label = self._make_label(text)
        row.addWidget(label)
        self._append_entry(frame)
        self._style_command_frame(frame, self._current_outline_color())

    def append_text(self, text: str) -> None:
        if text:
            self._append_entry(self._make_label(text))

    def _make_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        return label

    def _append_entry(self, widget: QWidget) -> None:
        self._log_layout.addWidget(widget)
        while self._log_layout.count() > self._MAX_ENTRIES:
            oldest = self._log_layout.takeAt(0)
            if oldest is not None and oldest.widget() is not None:
                oldest.widget().deleteLater()
        self._sync_content_geometry()
        self._schedule_scroll_to_bottom()

    def _schedule_scroll_to_bottom(self) -> None:
        if not self._scroll_pending:
            self._scroll_pending = True
            QTimer.singleShot(10, self._scroll_to_bottom)

    def _sync_content_geometry(self) -> None:
        contents = self.widget()
        if contents is None or not hasattr(self, "_log_layout"):
            return
        viewport_size = self.viewport().size()
        margins = self._log_layout.contentsMargins()
        entry_width = max(1, viewport_size.width() - margins.left() - margins.right())
        contents.resize(viewport_size.width(), 0)
        self._log_layout.activate()
        for index in range(self._log_layout.count()):
            item = self._log_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, QLabel):
                self._reset_height_constraint(widget)
                widget.setFixedHeight(self._label_height(widget, entry_width))
            elif isinstance(widget, QFrame):
                label = widget.findChild(QLabel)
                row = widget.layout()
                if label is None or row is None:
                    continue
                self._reset_height_constraint(widget)
                self._reset_height_constraint(label)
                row_margins = row.contentsMargins()
                label_width = max(
                    1,
                    entry_width - row_margins.left() - row_margins.right() - 2,
                )
                label_height = self._label_height(label, label_width)
                label.setFixedHeight(label_height)
                widget.setFixedHeight(label_height + row_margins.top() + row_margins.bottom() + 2)
        self._log_layout.invalidate()
        self._log_layout.activate()
        content_height = max(
            viewport_size.height(),
            self._log_layout.sizeHint().height(),
        )
        contents.resize(viewport_size.width(), content_height)
        self._log_layout.activate()

    @staticmethod
    def _reset_height_constraint(widget: QWidget) -> None:
        widget.setMinimumHeight(0)
        widget.setMaximumHeight(16_777_215)

    @staticmethod
    def _label_height(label: QLabel, width: int) -> int:
        if label.hasHeightForWidth():
            return max(1, label.heightForWidth(width))
        return label.sizeHint().height()

    def _scroll_to_bottom(self) -> None:
        self._sync_content_geometry()
        QTimer.singleShot(10, self._set_scroll_value_to_bottom)

    def _set_scroll_value_to_bottom(self) -> None:
        scroll_bar = self.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())
        self._scroll_pending = False

    def _current_outline_color(self) -> str:
        text_color = self.palette().color(QPalette.ColorRole.WindowText)
        return "#ffffff" if text_color.lightness() >= 128 else "#000000"

    @staticmethod
    def _style_command_frame(frame: QFrame, color: str) -> None:
        frame.setStyleSheet(f"QFrame#{frame.objectName()} {{ border: 1px solid {color}; }}")

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        last_command_frame = self.findChild(QFrame, "sgsActivityCommandLatest")
        if (
            event.type()
            in {
                QEvent.Type.PaletteChange,
                QEvent.Type.ApplicationPaletteChange,
            }
            and last_command_frame is not None
        ):
            self._style_command_frame(
                last_command_frame,
                self._current_outline_color(),
            )

    def resizeEvent(self, event: object) -> None:
        scroll_bar = self.verticalScrollBar()
        was_at_bottom = scroll_bar.value() >= scroll_bar.maximum()
        super().resizeEvent(event)
        self._sync_content_geometry()
        if was_at_bottom:
            self._schedule_scroll_to_bottom()


class _CommandWorker(QThread):
    """Run CLI commands away from the Qt event loop."""

    completed = Signal(object)

    def __init__(self, commands: list[list[str]]) -> None:
        super().__init__()
        self.commands = commands

    def run(self) -> None:
        results = []
        for arguments in self.commands:
            try:
                process = subprocess.run(
                    [sys.executable, "-m", "steam_game_switcher", *arguments],
                    capture_output=True,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                    text=True,
                )
                results.append(
                    CommandResult(
                        arguments=arguments,
                        return_code=process.returncode,
                        stdout=process.stdout,
                        stderr=process.stderr,
                    )
                )
            except OSError as error:
                results.append(CommandResult(arguments, 1, "", f"Could not start SGS: {error}\n"))
        self.completed.emit(results)


class SGSWindow(QMainWindow):
    """Main application window."""

    def __init__(
        self,
        config: Path,
        app_id: int,
        steamapps: Path | None = None,
        manifest: Path | None = None,
        steamcmd: str | None = None,
        guard: bool = False,
        initial_branch_mode: str = "automatic",
    ) -> None:
        super().__init__()
        self.config = config.expanduser()
        self._worker: _CommandWorker | None = None
        self._completion: Callable[[list[CommandResult]], None] | None = None
        self._loaded_branches: list[str] = []
        self._current_branch = ""

        self.setWindowTitle("Steam Game Switcher")
        self.resize(1050, 800)
        self.setWindowIcon(QIcon(str(application_icon_path())))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addLayout(self._build_game_header(app_id))
        self.locations_section = self._build_locations(steamapps, manifest, steamcmd, guard)
        layout.addWidget(self.locations_section)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_switch_tab(initial_branch_mode), "Branch")
        self.tabs.addTab(self._build_settings_tab(), "Game settings")
        self.tabs.addTab(self._build_defaults_tab(), "Defaults")
        self.tabs.addTab(self._build_backups_tab(), "Backups")
        self.tabs.addTab(self._build_shortcuts_tab(), "Shortcuts")
        self.tabs.addTab(self._build_steamcmd_tab(), "SteamCMD")
        layout.addWidget(self.tabs, 1)

        log_group = QGroupBox("Activity")
        log_layout = QVBoxLayout(log_group)
        self.activity = _ActivityLog()
        log_layout.addWidget(self.activity)
        layout.addWidget(log_group, 1)

        self._load_local_preferences()
        self._refresh_backups()
        self.refresh_game()

    def _build_game_header(self, app_id: int) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("Steam App ID"))
        self.app_id_input = QSpinBox()
        self.app_id_input.setRange(1, 2_147_483_647)
        self.app_id_input.setValue(app_id)
        self.app_id_input.setKeyboardTracking(False)
        self.app_id_input.setMaximumWidth(170)
        self.app_id_input.valueChanged.connect(self._app_id_changed)
        layout.addWidget(self.app_id_input)
        self.load_game_button = QPushButton("Load / refresh")
        self.load_game_button.clicked.connect(self.refresh_game)
        layout.addWidget(self.load_game_button)
        self.game_summary = QLabel("Loading game…")
        self.game_summary.setWordWrap(True)
        layout.addWidget(self.game_summary, 1)
        return layout

    def _build_locations(
        self,
        steamapps: Path | None,
        manifest: Path | None,
        steamcmd: str | None,
        guard: bool,
    ) -> QWidget:
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(2)

        self.locations_toggle = QToolButton()
        self.locations_toggle.setText("Locations and safety")
        self.locations_toggle.setCheckable(True)
        self.locations_toggle.setChecked(True)
        self.locations_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.locations_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.locations_toggle.setAutoRaise(True)
        section_layout.addWidget(self.locations_toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        self.locations_content = QGroupBox()
        section_layout.addWidget(self.locations_content)
        self.locations_toggle.toggled.connect(self._set_locations_expanded)
        self._set_locations_expanded(True)
        grid = QGridLayout(self.locations_content)
        grid.setContentsMargins(12, 2, 4, 4)

        grid.addWidget(QLabel("Config file"), 0, 0)
        self.config_input = QLineEdit(str(self.config))
        grid.addWidget(self.config_input, 0, 1)
        config_browse = QPushButton("Browse…")
        config_browse.clicked.connect(self._browse_config)
        grid.addWidget(config_browse, 0, 2)

        grid.addWidget(QLabel("Manifest location"), 1, 0)
        self.location_mode = QComboBox()
        self.location_mode.addItem("Auto-detect", "auto")
        self.location_mode.addItem("Steam steamapps folder", "steamapps")
        self.location_mode.addItem("Exact manifest file", "manifest")
        grid.addWidget(self.location_mode, 1, 1)
        self.location_path = QLineEdit()
        if manifest is not None:
            self.location_mode.setCurrentIndex(2)
            self.location_path.setText(str(manifest))
        elif steamapps is not None:
            self.location_mode.setCurrentIndex(1)
            self.location_path.setText(str(steamapps))
        grid.addWidget(self.location_path, 1, 2)
        self.location_browse = QPushButton("Browse…")
        self.location_browse.clicked.connect(self._browse_location)
        grid.addWidget(self.location_browse, 1, 3)
        self.location_mode.currentIndexChanged.connect(self._update_location_controls)
        self._update_location_controls()

        grid.addWidget(QLabel("SteamCMD executable"), 2, 0)
        self.steamcmd_input = QLineEdit(steamcmd or "")
        self.steamcmd_input.setPlaceholderText("Automatic detection")
        grid.addWidget(self.steamcmd_input, 2, 1, 1, 2)
        steamcmd_browse = QPushButton("Browse…")
        steamcmd_browse.clicked.connect(self._browse_steamcmd)
        grid.addWidget(steamcmd_browse, 2, 3)

        self.guard_input = QCheckBox(
            "Guard manifest edits if Steam may be running and SGS is not restarting it"
        )
        self.guard_input.setChecked(guard)
        grid.addWidget(self.guard_input, 3, 0, 1, 4)
        return section

    def _set_locations_expanded(self, expanded: bool) -> None:
        self.locations_content.setVisible(expanded)
        arrow = Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        self.locations_toggle.setArrowType(arrow)

    def _update_switch_button_text(self, dry_run: bool) -> None:
        text = "Preview branch switch" if dry_run else "Switch branch (instant)"
        self.switch_button.setText(text)

    def _build_switch_tab(self, initial_branch_mode: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls = QGridLayout()
        controls.addWidget(QLabel("Branch data"), 0, 0)
        self.branch_mode = QComboBox()
        self.branch_mode.addItem("Automatic (saved cache)", "automatic")
        self.branch_mode.addItem("Refresh from SteamCMD", "refresh")
        self.branch_mode.addItem("Use cached data", "cache")
        mode_index = {"automatic": 0, "refresh": 1, "cache": 2}.get(initial_branch_mode, 0)
        self.branch_mode.setCurrentIndex(mode_index)
        controls.addWidget(self.branch_mode, 0, 1)

        controls.addWidget(QLabel("Switch to"), 0, 2)
        self.branch_choice = QComboBox()
        self.branch_choice.setMinimumWidth(220)
        controls.addWidget(self.branch_choice, 0, 3)

        controls.addWidget(QLabel("Install folder override"), 1, 0)
        self.install_dir_input = QLineEdit()
        self.install_dir_input.setPlaceholderText("Optional folder name for the selected branch")
        controls.addWidget(self.install_dir_input, 1, 1, 1, 3)

        self.dry_run_input = QCheckBox("Preview only (dry run)")
        controls.addWidget(self.dry_run_input, 2, 0, 1, 2)
        self.switch_button = QPushButton("Switch branch (instant)")
        self.switch_button.setEnabled(False)
        self.switch_button.clicked.connect(self.switch_branch)
        self.dry_run_input.toggled.connect(self._update_switch_button_text)
        controls.addWidget(self.switch_button, 2, 3)
        layout.addLayout(controls)

        self.status_details = QPlainTextEdit()
        self.status_details.setReadOnly(True)
        self.status_details.setPlaceholderText("Game status appears here after loading.")
        layout.addWidget(self.status_details, 1)
        return widget

    def _build_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        group = QGroupBox("Preferences for this game")
        form = QFormLayout(group)
        self.separate_folders = QCheckBox("Use a separate install folder for each branch")
        self.restart_steam = QCheckBox("Restart Steam after a branch change")
        self.launch_after_switch = QCheckBox("Launch the game after a branch change")
        self.launch_when_unchanged = QCheckBox(
            "Launch the game when the requested branch is already active"
        )
        form.addRow(self.separate_folders)
        form.addRow(self.restart_steam)
        form.addRow(self.launch_after_switch)
        form.addRow(self.launch_when_unchanged)
        layout.addWidget(group)
        save = QPushButton("Save game settings")
        save.clicked.connect(self.save_game_settings)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return widget

    def _build_defaults_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        group = QGroupBox("Defaults for new games")
        form = QFormLayout(group)
        self.default_app_id_input = QSpinBox()
        self.default_app_id_input.setRange(1, 2_147_483_647)
        form.addRow("Default App ID", self.default_app_id_input)

        self.default_separate_folders = QCheckBox("Use separate install folders")
        self.default_restart_steam = QCheckBox("Restart Steam after a branch change")
        self.default_launch_after_switch = QCheckBox("Launch the game after a branch change")
        self.default_launch_when_unchanged = QCheckBox(
            "Launch when the requested branch is already active"
        )
        form.addRow(self.default_separate_folders)
        form.addRow(self.default_restart_steam)
        form.addRow(self.default_launch_after_switch)
        form.addRow(self.default_launch_when_unchanged)
        layout.addWidget(group)
        save = QPushButton("Save defaults")
        save.clicked.connect(self.save_defaults)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return widget

    def _build_backups_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        self.all_backups = QCheckBox("Show backups for every App ID")
        self.all_backups.toggled.connect(self._refresh_backups)
        controls.addWidget(self.all_backups)
        controls.addStretch(1)
        refresh = QPushButton("Refresh list")
        refresh.clicked.connect(self._refresh_backups)
        controls.addWidget(refresh)
        layout.addLayout(controls)

        self.backup_table = QTableWidget(0, 5)
        self.backup_table.setHorizontalHeaderLabels(
            ["#", "Branch", "App ID", "Created", "Backup ID"]
        )
        self.backup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.backup_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.backup_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.backup_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.backup_table, 1)

        buttons = QHBoxLayout()
        restore = QPushButton("Restore selected…")
        restore.clicked.connect(self.restore_backup)
        buttons.addWidget(restore)
        delete = QPushButton("Delete selected…")
        delete.clicked.connect(self.delete_backup)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return widget

    def _build_shortcuts_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Select one or more branches for launcher shortcuts:"))
        self.shortcut_branches = QListWidget()
        self.shortcut_branches.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.shortcut_branches, 1)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output folder"))
        self.shortcut_output = QLineEdit(str(default_shortcut_directory()))
        output_row.addWidget(self.shortcut_output, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_shortcut_directory)
        output_row.addWidget(browse)
        layout.addLayout(output_row)
        buttons = QHBoxLayout()
        self.replace_shortcuts = QCheckBox("Replace existing shortcuts")
        buttons.addWidget(self.replace_shortcuts)
        buttons.addStretch(1)
        create = QPushButton("Create shortcuts")
        create.clicked.connect(self.create_shortcuts)
        buttons.addWidget(create)
        layout.addLayout(buttons)
        return widget

    def _build_steamcmd_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(
            QLabel("Install or repair the user-local SteamCMD used to retrieve public branch data.")
        )
        buttons = QHBoxLayout()
        install = QPushButton("Install / check SteamCMD")
        install.clicked.connect(lambda: self.install_steamcmd(repair=False))
        buttons.addWidget(install)
        repair = QPushButton("Repair SteamCMD")
        repair.clicked.connect(lambda: self.install_steamcmd(repair=True))
        buttons.addWidget(repair)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return widget

    def _update_location_controls(self) -> None:
        mode = self.location_mode.currentData()
        self.location_path.setEnabled(mode != "auto")
        self.location_browse.setEnabled(mode != "auto")
        self.location_path.setPlaceholderText(
            "Path to Steam/steamapps" if mode == "steamapps" else "Path to appmanifest_<ID>.acf"
        )

    def _browse_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select config file",
            self.config_input.text(),
            "JSON files (*.json);;All files (*)",
        )
        if path:
            self.config_input.setText(path)

    def _browse_location(self) -> None:
        if self.location_mode.currentData() == "steamapps":
            path = QFileDialog.getExistingDirectory(
                self, "Select Steam steamapps folder", self.location_path.text()
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select appmanifest file", self.location_path.text(), "ACF files (*.acf)"
            )
        if path:
            self.location_path.setText(path)

    def _browse_steamcmd(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select SteamCMD executable", self.steamcmd_input.text()
        )
        if path:
            self.steamcmd_input.setText(path)

    def _browse_shortcut_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select shortcut output folder", self.shortcut_output.text()
        )
        if path:
            self.shortcut_output.setText(path)

    def _app_id(self) -> int:
        return self.app_id_input.value()

    def _app_id_changed(self, _app_id: int) -> None:
        self._load_local_preferences()
        self._refresh_backups()
        self._loaded_branches = []
        self.branch_choice.clear()
        self.shortcut_branches.clear()
        self.status_details.clear()
        self.switch_button.setEnabled(False)
        self.game_summary.setText(
            f"App ID {self._app_id()} selected — load the game to refresh branch status."
        )

    def _base_arguments(self, *, include_branch_mode: bool = False) -> list[str]:
        config = self.config_input.text().strip()
        if not config:
            raise SwitcherError("Choose a config file path.")
        arguments = ["--config", config, "--app-id", str(self._app_id())]
        mode = self.location_mode.currentData()
        location = self.location_path.text().strip()
        if mode != "auto":
            if not location:
                raise SwitcherError("Choose a manifest location or use auto-detect.")
            option = "--steamapps" if mode == "steamapps" else "--manifest"
            arguments.extend((option, location))
        steamcmd = self.steamcmd_input.text().strip()
        if steamcmd:
            arguments.extend(("--steamcmd", steamcmd))
        arguments.append("--guard" if self.guard_input.isChecked() else "--no-guard")
        if include_branch_mode:
            selected_mode = self.branch_mode.currentData()
            if selected_mode in {"refresh", "cache"}:
                arguments.append(f"--{selected_mode}")
        return arguments

    def _command(self, command: list[str], *, include_branch_mode: bool = False) -> list[str]:
        return [*self._base_arguments(include_branch_mode=include_branch_mode), *command]

    def _run_commands(
        self,
        commands: list[list[str]],
        completion: Callable[[list[CommandResult]], None] | None = None,
    ) -> None:
        if self._worker is not None:
            return
        self._set_busy(True)
        worker = _CommandWorker(commands)
        self._worker = worker
        self._completion = completion
        worker.completed.connect(self._commands_completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _commands_completed(self, results: list[CommandResult]) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.wait()
        self._set_busy(False)
        for result in results:
            rendered = " ".join(["sgs", *result.arguments])
            self.activity.append_command(f"$ {rendered}")
            if result.stdout.strip():
                self.activity.append_text(result.stdout.rstrip())
            if result.stderr.strip():
                self.activity.append_text(result.stderr.rstrip())
            if result.return_code:
                self.activity.append_text(f"Command exited with status {result.return_code}.")
        callback = self._completion
        self._completion = None
        if callback is not None:
            callback(results)

    def _set_busy(self, busy: bool) -> None:
        self.load_game_button.setEnabled(not busy)
        self.app_id_input.setEnabled(not busy)
        self.locations_section.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        self.switch_button.setEnabled(not busy and bool(self._loaded_branches))
        self.setWindowTitle("Steam Game Switcher — working…" if busy else "Steam Game Switcher")

    def _load_local_preferences(self) -> None:
        try:
            root, game = load_state(self.config_input_path(), self._app_id())
            self.separate_folders.setChecked(game["separate_install_dirs"])
            self.restart_steam.setChecked(game["restart_steam_on_switch"])
            self.launch_after_switch.setChecked(game["launch_game_after_switch"])
            self.launch_when_unchanged.setChecked(game["launch_game_when_unchanged"])
            self.default_app_id_input.setValue(root["default_app_id"])
            defaults = root["defaults"]
            self.default_separate_folders.setChecked(defaults["separate_install_dirs"])
            self.default_restart_steam.setChecked(defaults["restart_steam_on_switch"])
            self.default_launch_after_switch.setChecked(defaults["launch_game_after_switch"])
            self.default_launch_when_unchanged.setChecked(defaults["launch_game_when_unchanged"])
        except SwitcherError as error:
            self.activity.append_text(f"Could not load saved preferences: {error}")

    def config_input_path(self) -> Path:
        value = self.config_input.text().strip()
        return Path(value) if value else self.config

    def refresh_game(self) -> None:
        self._load_local_preferences()
        self._refresh_backups()
        self._loaded_branches = []
        self.branch_choice.clear()
        self.shortcut_branches.clear()
        self.status_details.clear()
        self.game_summary.setText(f"Loading App ID {self._app_id()}…")
        try:
            common = self._base_arguments()
            with_mode = self._base_arguments(include_branch_mode=True)
        except SwitcherError as error:
            self.game_summary.setText(str(error))
            return
        status_command = [*common, "status"]
        branches_command = [*with_mode, "branches"]
        self._run_commands(
            [branches_command, status_command],
            self._game_loaded,
        )

    def _game_loaded(self, results: list[CommandResult]) -> None:
        branch_result = results[0] if results else None
        status_result = results[1] if len(results) > 1 else None
        branches: list[str] = []
        if branch_result is not None and branch_result.return_code == 0:
            for line in branch_result.stdout.splitlines():
                match = re.match(r"^\s*\d+\.\s+(.*)$", line)
                if match:
                    label = match.group(1)
                    branches.append("" if label == "public" else label)
        self._loaded_branches = branches

        current_branch: str | None = None
        status_lines: list[str] = []
        if status_result is not None and status_result.return_code == 0:
            status_lines = status_result.stdout.strip().splitlines()
            for line in status_lines:
                if line.startswith("Branch: "):
                    current_branch = "" if line.removeprefix("Branch: ") == "public" else line[8:]
                    break

        self._current_branch = current_branch or ""
        for branch in branches:
            label = branch_label(branch)
            self.branch_choice.addItem(label, branch)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, branch)
            self.shortcut_branches.addItem(item)
        self.switch_button.setEnabled(bool(branches))
        selected = self.branch_choice.findData(self._current_branch)
        if selected >= 0:
            self.branch_choice.setCurrentIndex(selected)

        if status_result is not None and status_result.return_code == 0:
            self.status_details.setPlainText("\n".join(status_lines))
            self.game_summary.setText("  •  ".join(status_lines[:3]))
        else:
            self.game_summary.setText(f"App ID {self._app_id()} — manifest status unavailable")
        if branch_result is not None and branch_result.return_code:
            self.game_summary.setText(
                f"App ID {self._app_id()} — branch list unavailable; see Activity for details"
            )

    def switch_branch(self) -> None:
        branch = self.branch_choice.currentData()
        if branch is None:
            QMessageBox.information(
                self, "Branches not loaded", "Load the game's branch list first."
            )
            return
        target = branch or "public"
        command = ["switch", target]
        install_dir = self.install_dir_input.text().strip()
        if install_dir:
            command.extend(("--install-dir", install_dir))
        dry_run = self.dry_run_input.isChecked()
        if dry_run:
            command.append("--dry-run")
        full_command = self._command(command, include_branch_mode=True)
        if dry_run:
            self._run_commands(
                [full_command],
                lambda results: self._show_dry_run_result(results, branch_label(branch)),
            )
        else:
            self._run_commands(
                [full_command],
                lambda _: self._after_manifest_action(),
            )

    def _show_dry_run_result(self, results: list[CommandResult], target: str) -> None:
        result = results[0] if results else None
        if result is None:
            self.status_details.setPlainText("No output was received from the dry run.")
            self.game_summary.setText("Dry-run preview failed.")
            return

        report = "\n".join(part.rstrip() for part in (result.stdout, result.stderr) if part.strip())
        self.status_details.setPlainText(
            report or "The dry run completed without additional output."
        )
        if result.return_code == 0:
            self.game_summary.setText(
                f"Dry-run preview for {target} complete — no files were changed."
            )
        else:
            self.game_summary.setText(
                f"Dry-run preview for {target} failed — see the output below."
            )

    def save_game_settings(self) -> None:
        command = ["settings"]
        command.append(
            "--separate-folders" if self.separate_folders.isChecked() else "--shared-folder"
        )
        for enabled, positive, negative in (
            (
                self.restart_steam.isChecked(),
                "--restart-steam-on-switch",
                "--no-restart-steam-on-switch",
            ),
            (
                self.launch_after_switch.isChecked(),
                "--launch-game-after-switch",
                "--no-launch-game-after-switch",
            ),
            (
                self.launch_when_unchanged.isChecked(),
                "--launch-game-when-unchanged",
                "--no-launch-game-when-unchanged",
            ),
        ):
            command.append(positive if enabled else negative)
        self._run_commands(
            [self._command(command)],
            lambda _: self._load_local_preferences(),
        )

    def save_defaults(self) -> None:
        command = ["defaults", "--default-app-id", str(self.default_app_id_input.value())]
        command.append(
            "--separate-folders" if self.default_separate_folders.isChecked() else "--shared-folder"
        )
        for enabled, positive, negative in (
            (
                self.default_restart_steam.isChecked(),
                "--restart-steam",
                "--no-restart-steam",
            ),
            (
                self.default_launch_after_switch.isChecked(),
                "--launch-game",
                "--no-launch-game",
            ),
            (
                self.default_launch_when_unchanged.isChecked(),
                "--launch-game-when-unchanged",
                "--no-launch-game-when-unchanged",
            ),
        ):
            command.append(positive if enabled else negative)
        self._run_commands(
            [self._command(command)],
            lambda _: self._load_local_preferences(),
        )

    def _refresh_backups(self, *_args: object) -> None:
        try:
            store = load_backup_store(backup_store_path(self.config_input_path()))
            entries = _ordered_backups(store, self._app_id(), self.all_backups.isChecked())
        except SwitcherError as error:
            self.backup_table.setRowCount(0)
            self.activity.append_text(f"Could not load backups: {error}")
            return

        self.backup_table.setRowCount(len(entries))
        for index, entry in enumerate(entries, start=1):
            values = (
                str(index),
                branch_label(str(entry.get("branch") or "")),
                str(entry.get("app_id", "?")),
                str(entry.get("created_at", "unknown time")),
                str(entry.get("id", "?")),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.backup_table.setItem(index - 1, column, item)
        self.backup_table.resizeColumnsToContents()

    def _selected_backup_id(self) -> str | None:
        row = self.backup_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No backup selected", "Select a backup row first.")
            return None
        item = self.backup_table.item(row, 4)
        return item.text() if item is not None else None

    def restore_backup(self) -> None:
        backup_id = self._selected_backup_id()
        if backup_id is None:
            return
        row = self.backup_table.currentRow()
        app_id = self.backup_table.item(row, 2).text()
        branch = self.backup_table.item(row, 1).text()
        answer = QMessageBox.question(
            self,
            "Confirm restore",
            f"Restore backup {backup_id} for App ID {app_id} ({branch})?\n\n"
            "The current manifest, when present, will be backed up first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_commands(
            [self._command(["backup", "restore", backup_id])],
            lambda _: self._after_manifest_action(),
        )

    def delete_backup(self) -> None:
        backup_id = self._selected_backup_id()
        if backup_id is None:
            return
        row = self.backup_table.currentRow()
        app_id = self.backup_table.item(row, 2).text()
        branch = self.backup_table.item(row, 1).text()
        answer = QMessageBox.question(
            self,
            "Confirm deletion",
            f"Delete backup {backup_id} for App ID {app_id} ({branch})?\n"
            "This does not change the live manifest.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_commands(
            [self._command(["backup", "delete", backup_id, "--yes"])],
            lambda _: self._refresh_backups(),
        )

    def create_shortcuts(self) -> None:
        selections = [
            str(item.data(Qt.ItemDataRole.UserRole) or "public")
            for item in self.shortcut_branches.selectedItems()
        ]
        if not selections:
            QMessageBox.information(self, "No branches selected", "Select at least one branch.")
            return
        output = self.shortcut_output.text().strip()
        if not output:
            QMessageBox.information(self, "Output folder required", "Choose an output folder.")
            return
        command = ["shortcuts", "--output", output]
        if self.replace_shortcuts.isChecked():
            answer = QMessageBox.question(
                self,
                "Confirm shortcut replacement",
                "Replace any existing shortcut files for the selected branches?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            command.append("--force")
        command.extend(("--", *selections))
        self._run_commands([self._command(command, include_branch_mode=True)])

    def install_steamcmd(self, *, repair: bool) -> None:
        action = "repair" if repair else "install or check"
        answer = QMessageBox.question(
            self,
            "Confirm SteamCMD setup",
            f"Start SteamCMD {action} for the current user?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        command = ["steamcmd", "repair" if repair else "install"]
        self._run_commands([self._command(command)])

    def _after_manifest_action(self) -> None:
        self._load_local_preferences()
        self._refresh_backups()
        self.refresh_game()

    def closeEvent(self, event: object) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self,
                "Operation in progress",
                "Wait for the current SGS operation to finish before closing the window.",
            )
            event.ignore()
            return
        event.accept()


def launch_gui(
    config: Path,
    app_id: int,
    steamapps: Path | None = None,
    manifest: Path | None = None,
    steamcmd: str | None = None,
    guard: bool = False,
    refresh: bool = False,
    cache: bool = False,
) -> int:
    """Start the optional GUI and return its Qt event-loop status."""
    from PySide6.QtWidgets import QApplication

    desktop_entry: Path | None = None
    desktop_entry_error: OSError | None = None
    try:
        desktop_entry = install_application_desktop_entry()
    except OSError as error:
        desktop_entry_error = error

    application = QApplication.instance()
    if application is None:
        application = QApplication(sys.argv[:1])
    application.setApplicationName("Steam Game Switcher")
    application.setApplicationDisplayName("Steam Game Switcher")
    application.setDesktopFileName(DESKTOP_FILE_NAME)
    application.setWindowIcon(QIcon(str(application_icon_path())))
    mode = "refresh" if refresh else "cache" if cache else "automatic"
    window = SGSWindow(
        config=config,
        app_id=app_id,
        steamapps=steamapps,
        manifest=manifest,
        steamcmd=steamcmd,
        guard=guard,
        initial_branch_mode=mode,
    )
    if desktop_entry is not None:
        window.activity.append_text(f"App menu launcher: {desktop_entry}")
    elif desktop_entry_error is not None:
        window.activity.append_text(f"Could not install app menu launcher: {desktop_entry_error}")
    window.show()

    previous_sigint_handler = signal.getsignal(signal.SIGINT)
    interrupted = False

    def _quit_on_interrupt(_signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True
        QTimer.singleShot(0, application.quit)

    try:
        signal.signal(signal.SIGINT, _quit_on_interrupt)
    except ValueError:
        signal_handler_installed = False
        interrupt_timer = None
    else:
        signal_handler_installed = True
        interrupt_timer = QTimer(application)
        interrupt_timer.setInterval(100)
        interrupt_timer.timeout.connect(lambda: None)
        interrupt_timer.start()

    try:
        exit_code = application.exec()
    finally:
        if interrupt_timer is not None:
            interrupt_timer.stop()
        worker = window._worker
        if worker is not None and worker.isRunning():
            worker.wait()
        window.close()
        window.deleteLater()
        application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if signal_handler_installed:
            signal.signal(signal.SIGINT, previous_sigint_handler)
    return 128 + signal.SIGINT if interrupted else exit_code
