from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QTableWidgetItem

from metajot.ai import ADOBE_CATEGORY_IDS
from metajot.location import Location
from metajot.metadata import ImageMetadata

# Reverse of ai.ADOBE_CATEGORY_IDS, to map the numeric ID stored on disk back
# to the category name shown to the user.
ADOBE_CATEGORY_NAMES_BY_ID = {str(v): k for k, v in ADOBE_CATEGORY_IDS.items()}


@dataclass
class RowState:
    """A photo's metadata as shown in the GUI - the source of truth for
    writing and exporting, independent of the table's (sortable) row order."""

    path: Path
    current_meta: Optional[ImageMetadata] = None
    title: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    location: Optional[Location] = None
    adobe_category_id: Optional[str] = None
    shutterstock_categories: list[str] = field(default_factory=list)
    status: str = "Pending"
    # Status to show when there are no unsaved changes ("Pending", "Done",
    # "Written").
    clean_status: str = "Pending"
    # Has MetaJot metadata (on disk from a previous run, or freshly
    # generated) - i.e. categories etc. are meaningful enough to export.
    processed: bool = False
    # Has AI-generated values not yet written to the file.
    dirty: bool = False
    # The editorial flag as last read from / written to the file, to tell
    # whether the Editorial checkbox has an unsaved change.
    saved_editorial: bool = False
    # The table items showing this row, which stay attached to it however
    # the table is sorted.
    process_item: Optional[QTableWidgetItem] = None
    title_item: Optional[QTableWidgetItem] = None
    editorial_item: Optional[QTableWidgetItem] = None
    status_item: Optional[QTableWidgetItem] = None

    def set_status(self, status: str) -> None:
        self.status = status
        if self.status_item:
            self.status_item.setText(status)

    def set_title(self, title: str) -> None:
        self.title = title
        if self.title_item:
            self.title_item.setText(title)

    @property
    def editorial(self) -> bool:
        return _is_checked(self.editorial_item)

    @property
    def editorial_changed(self) -> bool:
        return self.editorial != self.saved_editorial

    @property
    def has_unsaved_changes(self) -> bool:
        return self.dirty or self.editorial_changed

    @property
    def selected_for_processing(self) -> bool:
        return _is_checked(self.process_item)

    def set_selected_for_processing(self, selected: bool) -> None:
        if self.process_item:
            self.process_item.setCheckState(
                Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
            )


def _is_checked(item: Optional[QTableWidgetItem]) -> bool:
    return bool(item and item.checkState() == Qt.CheckState.Checked)


def load_thumbnail(path: Path, size: int) -> QPixmap:
    """Decodes directly at thumbnail resolution instead of full size, since
    these source JPEGs are commonly 10+ MB."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original_size = reader.size()
    if original_size.isValid():
        scaled = original_size.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(scaled)
    return QPixmap.fromImage(reader.read())
