from __future__ import annotations

from pathlib import Path
from fnmatch import fnmatch

from PyQt5.QtCore import QMetaObject, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QScrollArea,
)
from krita import Krita

from . import theme
from .theme import SignalBlocker
from .settings_widgets import ExpanderButton
from ..model import Model
from ..root import root
from ..localization import translate as _
from ..properties import Binding, Bind, bind
from ..files import File, FileSource
from .widget import WorkspaceSelectWidget


class LoraFolderWidget(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None):
        super().__init__(parent)

        self._expander = ExpanderButton(name, self)

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 0, 0, 0)
        self._content_layout.setSpacing(2)
        self._content.setLayout(self._content_layout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._expander)
        layout.addWidget(self._content)
        self.setLayout(layout)

        self._expander.toggled.connect(self._content.setVisible)
        self._content.setVisible(self._expander.isChecked())

    def add_item(self, item: QWidget):
        self._content_layout.addWidget(item)


class LoraManagerItem(QWidget):
    def __init__(self, file: File, parent: QWidget | None = None):
        super().__init__(parent)

        self._file = file

        name_label = QLabel(file.name, self)

        self._trigger_edit = QLineEdit(self)
        trigger_help = _("Optional text which is added to the prompt when the LoRA is used")
        self._trigger_edit.setPlaceholderText(trigger_help)
        self._trigger_edit.setText(self._file.meta("lora_triggers", ""))
        self._trigger_edit.textChanged.connect(self._set_triggers)

        self._strength = QSpinBox(self)
        self._strength.setMinimum(0)
        self._strength.setMaximum(400)
        self._strength.setSingleStep(5)
        self._strength.setPrefix(_("Strength") + ": ")
        self._strength.setSuffix("%")
        strength_value = int(self._file.meta("lora_strength", 1.0) * 100)
        self._strength.setValue(strength_value)
        self._strength.valueChanged.connect(self._set_strength)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(name_label, 1)
        layout.addWidget(self._trigger_edit, 3)
        layout.addWidget(self._strength, 0)
        self.setLayout(layout)

    def _set_triggers(self, value: str):
        if self._file.meta("lora_triggers") != value:
            root.files.loras.set_meta(self._file, "lora_triggers", value)

    def _set_strength(self, value: int):
        strength = value / 100
        if self._file.meta("lora_strength") != strength:
            root.files.loras.set_meta(self._file, "lora_strength", strength)


class LoraManagerWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._model: Model = root.active_model
        self._model_bindings: list[QMetaObject.Connection | Binding] = []
        self._items: list[LoraManagerItem] = []
        self._groups: list[LoraFolderWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 4, 0)
        self.setLayout(layout)

        self.workspace_select = WorkspaceSelectWidget(self)
        self._filter_combo = QComboBox(self)
        self._filter_combo.currentIndexChanged.connect(self._filter_changed)
        self._refresh_button = QToolButton(self)
        self._refresh_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._refresh_button.setIcon(Krita.instance().icon("reload-preset"))
        self._refresh_button.setToolTip(_("Look for new LoRA files"))
        self._refresh_button.clicked.connect(root.connection.refresh)
        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText(_("Search LoRA"))
        self._search_input.textChanged.connect(self._filter_changed)
        self._settings_button = QToolButton(self)
        self._settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._settings_button.setIcon(theme.icon("settings"))
        self._settings_button.setAutoRaise(True)
        self._settings_button.setToolTip(_("Open settings"))
        self._settings_button.clicked.connect(self._show_settings)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self.workspace_select)
        header_layout.addWidget(self._filter_combo)
        header_layout.addWidget(self._refresh_button)
        header_layout.addWidget(self._search_input, 1)
        header_layout.addWidget(self._settings_button)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setAlignment(
            Qt.AlignmentFlag(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        )
        self._list_container = QWidget(self._scroll_area)
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_container.setLayout(self._list_layout)
        self._scroll_area.setWidget(self._list_container)
        layout.addWidget(self._scroll_area)

        root.files.loras.rowsInserted.connect(self._collect_filters)
        root.files.loras.rowsRemoved.connect(self._collect_filters)
        self._collect_filters()

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, model: Model):
        if self._model != model:
            Binding.disconnect_all(self._model_bindings)
            self._model = model
            self._model_bindings = [
                bind(model, "workspace", self.workspace_select, "value", Bind.one_way),
            ]

    def _show_settings(self):
        Krita.instance().action("ai_diffusion_settings").trigger()

    def _collect_filters(self):
        with SignalBlocker(self._filter_combo):
            self._filter_combo.clear()
            self._filter_combo.addItem(theme.icon("filter"), "All")
            folders: set[str] = set()
            for lora in root.files.loras:
                if lora.source is not FileSource.unavailable:
                    parts = Path(lora.id).parts
                    for i in range(1, len(parts)):
                        folders.add("/".join(parts[:i]))
            folder_icon = Krita.instance().icon("document-open")
            for folder in sorted(folders, key=lambda x: x.lower()):
                self._filter_combo.addItem(folder_icon, folder)
        self._rebuild_items()

    def _filter_changed(self, index: int):
        _ = index  # unused
        self._rebuild_items()

    def _rebuild_items(self):
        # Clear existing widgets and spacers from the list layout
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        self._items.clear()
        self._groups.clear()

        current_filter = (
            self._filter_combo.currentText() if self._filter_combo.count() > 0 else "All"
        )
        filter_prefix = "" if current_filter == "All" else current_filter

        search_text = self._search_input.text().strip().lower()
        pattern = f"*{search_text}*" if search_text else ""
        has_search = bool(pattern)

        loras = sorted(
            [file for file in root.files.loras if file.source is not FileSource.unavailable],
            key=lambda f: f.name.lower(),
        )

        root_files: list[File] = []
        folders: dict[str, list[File]] = {}

        for file in loras:
            relative_id = "/".join(Path(file.id).parts)
            if filter_prefix and not relative_id.startswith(filter_prefix):
                continue
            if has_search:
                name = file.name.lower()
                rel = relative_id.lower()
                if not (fnmatch(name, pattern) or fnmatch(rel, pattern)):
                    continue

            # Determine folder relative to current filter prefix
            rel_after_prefix = (
                relative_id[len(filter_prefix) :].lstrip("/") if filter_prefix else relative_id
            )
            parts = rel_after_prefix.split("/")

            # When searching, show all results flat at the top
            if has_search:
                root_files.append(file)
            else:
                if len(parts) == 1:
                    root_files.append(file)
                else:
                    folder = parts[0]
                    folders.setdefault(folder, []).append(file)

        # Add files without subfolder at top level
        for file in root_files:
            item = LoraManagerItem(file, self._list_container)
            self._list_layout.addWidget(item)
            self._items.append(item)

        # Add grouped files under foldouts (only when not searching)
        if not has_search:
            for folder_name in sorted(folders.keys(), key=lambda x: x.lower()):
                group_widget = LoraFolderWidget(folder_name, self._list_container)
                for file in folders[folder_name]:
                    item = LoraManagerItem(file, group_widget)
                    group_widget.add_item(item)
                    self._items.append(item)
                self._list_layout.addWidget(group_widget)
                self._groups.append(group_widget)

        self._list_layout.addStretch()
