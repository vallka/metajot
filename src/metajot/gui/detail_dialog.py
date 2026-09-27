from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from metajot.gui.row_state import ADOBE_CATEGORY_NAMES_BY_ID, RowState, load_thumbnail
from metajot.location import format_editorial_date

PREVIEW_SIZE = 560


class DetailDialog(QDialog):
    """Read-only view of all of a photo's metadata, opened from the list."""

    def __init__(self, state: RowState, parent=None):
        super().__init__(parent)
        self.setWindowTitle(state.path.name)
        self.resize(1150, 620)

        layout = QHBoxLayout(self)

        preview = QLabel()
        preview.setPixmap(load_thumbnail(state.path, PREVIEW_SIZE))
        preview.setFixedWidth(PREVIEW_SIZE)
        layout.addWidget(preview)

        right = QVBoxLayout()
        form = QFormLayout()
        meta = state.current_meta

        form.addRow("Filename:", self._line(state.path.name))
        form.addRow("Status:", self._line(state.status))
        form.addRow("Editorial:", self._line("Yes" if state.editorial else "No"))
        form.addRow("Title:", self._line(state.title))
        form.addRow("Description:", self._text(state.description, height=110))
        form.addRow("Keywords:", self._text(", ".join(state.keywords), height=110))

        location = state.location
        form.addRow("City:", self._line(location.city if location else None))
        form.addRow(
            "State/Province:",
            self._line(location.province_state if location else None),
        )
        form.addRow("Country:", self._line(location.country if location else None))

        adobe_name = ADOBE_CATEGORY_NAMES_BY_ID.get(state.adobe_category_id or "")
        form.addRow("Adobe category:", self._line(adobe_name))
        categories = state.shutterstock_categories
        form.addRow(
            "Shutterstock 1:", self._line(categories[0] if categories else None)
        )
        form.addRow(
            "Shutterstock 2:",
            self._line(categories[1] if len(categories) > 1 else None),
        )

        date_created = meta.date_created if meta else None
        form.addRow(
            "Date created:",
            self._line(format_editorial_date(date_created) if date_created else None),
        )
        gps = None
        if meta and meta.gps_latitude is not None and meta.gps_longitude is not None:
            gps = f"{meta.gps_latitude:.5f}, {meta.gps_longitude:.5f}"
        form.addRow("GPS:", self._line(gps))
        form.addRow(
            "Processed at:", self._line(meta.processed_at if meta else None)
        )

        right.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        layout.addLayout(right, 1)

    @staticmethod
    def _line(value) -> QLineEdit:
        edit = QLineEdit(value or "")
        edit.setReadOnly(True)
        edit.setCursorPosition(0)
        return edit

    @staticmethod
    def _text(value: str, height: int) -> QPlainTextEdit:
        edit = QPlainTextEdit(value or "")
        edit.setReadOnly(True)
        edit.setFixedHeight(height)
        return edit
