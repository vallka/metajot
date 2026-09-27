import re
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from metajot.ai import (
    ADOBE_CATEGORY_IDS,
    MAX_KEYWORDS,
    MAX_TITLE_CHARS,
    AdobeStockCategory,
    ShutterstockCategory,
)
from metajot.gui.row_state import ADOBE_CATEGORY_NAMES_BY_ID, RowState, load_thumbnail
from metajot.location import Location, format_editorial_date
from metajot.sanitize import sanitize_typography

PREVIEW_SIZE = 560
NONE_CHOICE = "(none)"
OVER_LIMIT_STYLE = "color: #c0392b; font-weight: bold;"
COUNTER_STYLE = "color: gray;"


def parse_keywords(text: str) -> list[str]:
    """Splits comma/newline-separated keywords, dropping blanks and
    case-insensitive duplicates while keeping the original order."""
    seen: set[str] = set()
    keywords = []
    for keyword in re.split(r"[,\n]", text):
        keyword = sanitize_typography(keyword).strip()
        if keyword and keyword.lower() not in seen:
            seen.add(keyword.lower())
            keywords.append(keyword)
    return keywords


@dataclass
class EditedValues:
    title: str
    description: str
    keywords: list[str]
    location: Location
    adobe_category_id: Optional[str]
    shutterstock_categories: list[str]

    def apply_to(self, state: RowState) -> None:
        state.set_title(self.title)
        state.description = self.description
        state.keywords = self.keywords
        state.location = None if self.location.is_empty() else self.location
        state.adobe_category_id = self.adobe_category_id
        state.shutterstock_categories = self.shutterstock_categories


class DetailDialog(QDialog):
    """A photo's full metadata, opened from the list, with Previous/Next to
    step through `states` (the list's current sort order). Title,
    description, keywords, location and categories are editable unless
    editable=False (e.g. while the AI is running). Saved edits are applied
    to the RowState and reported through on_saved(state)."""

    def __init__(
        self,
        states: list[RowState],
        index: int,
        parent=None,
        editable: bool = True,
        on_saved: Optional[Callable[[RowState], None]] = None,
    ):
        super().__init__(parent)
        self.states = states
        self.index = index
        self.editable = editable
        self.on_saved = on_saved
        self.resize(1200, 700)

        layout = QHBoxLayout(self)

        self.preview = QLabel()
        self.preview.setFixedWidth(PREVIEW_SIZE)
        layout.addWidget(self.preview)

        right = QVBoxLayout()
        form = QFormLayout()

        self.filename_edit = self._readonly()
        self.status_edit = self._readonly()
        self.editorial_check = QCheckBox("Editorial use")
        self.editorial_check.setToolTip(
            "Formats the Shutterstock description as an editorial dateline "
            "when exporting CSVs. Same as the Editorial checkbox in the list."
        )
        form.addRow("Filename:", self.filename_edit)
        form.addRow("Status:", self.status_edit)
        form.addRow("Editorial:", self.editorial_check)

        self.title_edit = QLineEdit()
        self.title_count = QLabel()
        form.addRow("Title:", self.title_edit)
        form.addRow("", self.title_count)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(110)
        form.addRow("Description:", self.description_edit)

        self.keywords_edit = QPlainTextEdit()
        self.keywords_edit.setFixedHeight(110)
        self.keywords_edit.setToolTip(
            "Comma-separated. Duplicates are removed on save."
        )
        self.keywords_count = QLabel()
        form.addRow("Keywords:", self.keywords_edit)
        form.addRow("", self.keywords_count)

        self.city_edit = QLineEdit()
        self.state_edit = QLineEdit()
        self.state_edit.setToolTip("For US locations, the two-letter state code (NY).")
        self.country_edit = QLineEdit()
        form.addRow("City:", self.city_edit)
        form.addRow("State/Province:", self.state_edit)
        form.addRow("Country:", self.country_edit)

        self.adobe_combo = self._combo([c.value for c in AdobeStockCategory])
        form.addRow("Adobe category:", self.adobe_combo)
        shutter_values = [c.value for c in ShutterstockCategory]
        self.shutter1_combo = self._combo(shutter_values)
        self.shutter2_combo = self._combo(shutter_values)
        form.addRow("Shutterstock 1:", self.shutter1_combo)
        form.addRow("Shutterstock 2:", self.shutter2_combo)

        self.date_edit = self._readonly()
        self.gps_edit = self._readonly()
        self.processed_at_edit = self._readonly()
        form.addRow("Date created:", self.date_edit)
        form.addRow("GPS:", self.gps_edit)
        form.addRow("Processed at:", self.processed_at_edit)

        right.addLayout(form)

        bottom = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.setShortcut(QKeySequence("Alt+Left"))
        self.prev_btn.setToolTip("Previous photo in the list order (Alt+Left)")
        self.prev_btn.clicked.connect(lambda: self._move(-1))
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setShortcut(QKeySequence("Alt+Right"))
        self.next_btn.setToolTip("Next photo in the list order (Alt+Right)")
        self.next_btn.clicked.connect(lambda: self._move(1))
        self.position_label = QLabel()
        bottom.addWidget(self.prev_btn)
        bottom.addWidget(self.next_btn)
        bottom.addWidget(self.position_label)
        bottom.addStretch(1)

        if editable:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(self._ok)
        else:
            note = QLabel("Read-only while photos are being processed.")
            note.setStyleSheet(COUNTER_STYLE)
            bottom.addWidget(note)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            for widget in (
                self.title_edit,
                self.city_edit,
                self.state_edit,
                self.country_edit,
                self.description_edit,
                self.keywords_edit,
            ):
                widget.setReadOnly(True)
            for combo in (self.adobe_combo, self.shutter1_combo, self.shutter2_combo):
                combo.setEnabled(False)
            self.editorial_check.setEnabled(False)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        right.addLayout(bottom)
        layout.addLayout(right, 1)

        self.title_edit.textChanged.connect(self._update_counters)
        self.keywords_edit.textChanged.connect(self._update_counters)

        # The widget values right after a photo is loaded, cleaned up the
        # same way as edits are. Changes are detected against this rather
        # than against the RowState, so the cleanup itself (trimming,
        # de-duplicating keywords, plain quotes, ...) never counts as an
        # edit - only something the user actually changed does.
        self._loaded_values: Optional[EditedValues] = None
        self._load()

    @property
    def state(self) -> RowState:
        return self.states[self.index]

    @staticmethod
    def _readonly() -> QLineEdit:
        edit = QLineEdit()
        edit.setReadOnly(True)
        return edit

    @staticmethod
    def _set_readonly_text(edit: QLineEdit, value: Optional[str]) -> None:
        edit.setText(value or "")
        edit.setCursorPosition(0)

    @staticmethod
    def _combo(values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItem(NONE_CHOICE)
        combo.addItems(values)
        return combo

    def _load(self) -> None:
        """Shows the current photo's values in the widgets."""
        state = self.state
        meta = state.current_meta
        self.setWindowTitle(state.path.name)
        self.preview.setPixmap(load_thumbnail(state.path, PREVIEW_SIZE))

        self._set_readonly_text(self.filename_edit, state.path.name)
        self._set_readonly_text(self.status_edit, state.status)
        self.editorial_check.setChecked(state.editorial)

        self.title_edit.setText(state.title)
        self.title_edit.setCursorPosition(0)
        self.description_edit.setPlainText(state.description)
        self.keywords_edit.setPlainText(", ".join(state.keywords))

        location = state.location or Location()
        self.city_edit.setText(location.city or "")
        self.state_edit.setText(location.province_state or "")
        self.country_edit.setText(location.country or "")

        adobe_name = ADOBE_CATEGORY_NAMES_BY_ID.get(state.adobe_category_id or "")
        self.adobe_combo.setCurrentText(adobe_name or NONE_CHOICE)
        categories = state.shutterstock_categories
        self.shutter1_combo.setCurrentText(categories[0] if categories else NONE_CHOICE)
        self.shutter2_combo.setCurrentText(
            categories[1] if len(categories) > 1 else NONE_CHOICE
        )

        date_created = meta.date_created if meta else None
        date_text = format_editorial_date(date_created) if date_created else None
        self._set_readonly_text(self.date_edit, date_text)
        gps = None
        if meta and meta.gps_latitude is not None and meta.gps_longitude is not None:
            gps = f"{meta.gps_latitude:.5f}, {meta.gps_longitude:.5f}"
        self._set_readonly_text(self.gps_edit, gps)
        self._set_readonly_text(
            self.processed_at_edit, meta.processed_at if meta else None
        )

        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.states) - 1)
        self.position_label.setText(f"{self.index + 1} of {len(self.states)}")
        self._update_counters()
        self._loaded_values = self.edited_values()
        self._loaded_editorial = self.editorial_check.isChecked()

    @staticmethod
    def _set_counter(label: QLabel, count: int, limit: int, over_hint: str) -> None:
        over = count > limit
        label.setText(f"{count} / {limit}" + (f" - {over_hint}" if over else ""))
        label.setStyleSheet(OVER_LIMIT_STYLE if over else COUNTER_STYLE)

    def _update_counters(self) -> None:
        # Warnings only - Adobe Stock's limits; nothing is blocked or trimmed.
        self._set_counter(
            self.title_count,
            len(self.title_edit.text().strip()),
            MAX_TITLE_CHARS,
            "too long for Adobe Stock",
        )
        self._set_counter(
            self.keywords_count,
            len(parse_keywords(self.keywords_edit.toPlainText())),
            MAX_KEYWORDS,
            "Adobe Stock allows at most 49",
        )

    @staticmethod
    def _choice(combo: QComboBox) -> Optional[str]:
        text = combo.currentText()
        return None if text == NONE_CHOICE else text

    def edited_values(self) -> EditedValues:
        """The values currently in the widgets, cleaned up."""
        adobe_name = self._choice(self.adobe_combo)
        shutterstock_categories: list[str] = []
        choices = (self._choice(self.shutter1_combo), self._choice(self.shutter2_combo))
        for choice in choices:
            if choice and choice not in shutterstock_categories:
                shutterstock_categories.append(choice)
        return EditedValues(
            title=sanitize_typography(self.title_edit.text()).strip(),
            description=sanitize_typography(
                self.description_edit.toPlainText()
            ).strip(),
            keywords=parse_keywords(self.keywords_edit.toPlainText()),
            location=Location(
                city=self.city_edit.text().strip() or None,
                province_state=self.state_edit.text().strip() or None,
                country=self.country_edit.text().strip() or None,
            ),
            adobe_category_id=(
                str(ADOBE_CATEGORY_IDS[adobe_name]) if adobe_name else None
            ),
            shutterstock_categories=shutterstock_categories,
        )

    def _content_changed(self) -> bool:
        return self.edited_values() != self._loaded_values

    def _editorial_changed(self) -> bool:
        return self.editorial_check.isChecked() != self._loaded_editorial

    def has_changes(self) -> bool:
        return self.editable and (
            self._content_changed() or self._editorial_changed()
        )

    def save(self) -> None:
        """Applies the current photo's edits (if any) to its RowState."""
        if not self.editable:
            return
        # The Editorial flag is tracked on its own (it's saved with a
        # flag-only write), so it goes through the list's checkbox rather
        # than counting as a metadata edit.
        if self._editorial_changed():
            self.state.set_editorial(self.editorial_check.isChecked())
        if self._content_changed():
            self.edited_values().apply_to(self.state)
            if self.on_saved:
                self.on_saved(self.state)

    def _move(self, step: int) -> None:
        target = self.index + step
        if not 0 <= target < len(self.states):
            return
        if self.has_changes():
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                f"Save your changes to {self.state.path.name}?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save:
                self.save()
        self.index = target
        self._load()

    def _ok(self) -> None:
        self.save()
        self.accept()
