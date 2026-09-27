from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from metajot.ai import (
    ADOBE_CATEGORY_IDS,
    AdobeStockCategory,
    AIResponse,
    ShutterstockCategory,
    build_shutterstock_description,
    resolve_editorial_dateline,
    resolve_location,
)
from metajot.exporter import (
    ExportRecord,
    export_adobe_stock_csv,
    export_shutterstock_csv,
)
from metajot.gui.worker import ProcessingWorker
from metajot.location import Location
from metajot.metadata import (
    ImageMetadata,
    read_metadata,
    resolve_deterministic_location,
    write_metadata,
)

THUMBNAIL_SIZE = 96
NO_SECONDARY = "(none)"

COL_THUMB = 0
COL_FILENAME = 1
COL_TITLE = 2
COL_DESCRIPTION = 3
COL_KEYWORDS = 4
COL_CITY = 5
COL_STATE = 6
COL_COUNTRY = 7
COL_ADOBE_CATEGORY = 8
COL_SHUTTER_PRIMARY = 9
COL_SHUTTER_SECONDARY = 10
COL_EDITORIAL = 11
COL_STATUS = 12
COLUMN_COUNT = 13

COLUMN_HEADERS = [
    "",
    "Filename",
    "Title",
    "Description",
    "Keywords",
    "City",
    "State/Province",
    "Country",
    "Adobe Category",
    "Shutterstock 1",
    "Shutterstock 2",
    "Editorial",
    "Status",
]

# Text columns whose edits are saved into the file by "Write Metadata".
EDITABLE_TEXT_COLUMNS = {
    COL_TITLE,
    COL_DESCRIPTION,
    COL_KEYWORDS,
    COL_CITY,
    COL_STATE,
    COL_COUNTRY,
}

# Reverse of ai.ADOBE_CATEGORY_IDS, to map the numeric ID stored on disk back
# to the category name the combo box displays.
ADOBE_CATEGORY_NAMES_BY_ID = {str(v): k for k, v in ADOBE_CATEGORY_IDS.items()}


@dataclass
class RowState:
    path: Path
    current_meta: Optional[ImageMetadata] = None
    # Has MetaJot metadata (on disk from a previous run, or freshly
    # generated) - i.e. categories etc. are meaningful enough to export.
    processed: bool = False
    # Has AI-generated values or user edits not yet written to the file.
    dirty: bool = False


def load_thumbnail(path: Path, size: int = THUMBNAIL_SIZE) -> QPixmap:
    """Decodes directly at thumbnail resolution instead of full size, since
    these source JPEGs are commonly 10+ MB."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original_size = reader.size()
    if original_size.isValid():
        scaled = original_size.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio
        )
        reader.setScaledSize(scaled)
    return QPixmap.fromImage(reader.read())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MetaJot")
        self.resize(1500, 700)

        self.directory: Optional[Path] = None
        self.rows: list[RowState] = []
        self.worker: Optional[ProcessingWorker] = None
        # Set while cells are filled programmatically, so only real user
        # edits mark a row as modified.
        self._populating = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        select_btn = QPushButton("Select Folder...")
        select_btn.clicked.connect(self.select_folder)
        self.folder_label = QLabel("No folder selected")
        self.process_btn = QPushButton("Process with AI")
        self.process_btn.clicked.connect(self.start_processing)
        self.write_btn = QPushButton("Write Metadata")
        self.write_btn.setToolTip(
            "Save the table's title, description, keywords, location and "
            "categories into the photo files."
        )
        self.write_btn.clicked.connect(self.write_metadata_clicked)
        self.export_btn = QPushButton("Export CSVs")
        self.export_btn.setToolTip(
            "Write adobe_stock.csv and shutterstock.csv for all processed "
            "photos in this folder."
        )
        self.export_btn.clicked.connect(self.export_csvs)
        top_bar.addWidget(select_btn)
        top_bar.addWidget(self.folder_label, 1)
        top_bar.addWidget(self.process_btn)
        top_bar.addWidget(self.write_btn)
        top_bar.addWidget(self.export_btn)
        layout.addLayout(top_bar)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.table = QTableWidget(0, COLUMN_COUNT)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            COL_DESCRIPTION, QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setDefaultSectionSize(THUMBNAIL_SIZE + 8)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self._update_buttons()

    def select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select photo folder")
        if not folder:
            return
        self.directory = Path(folder)
        self.folder_label.setText(str(self.directory))

        images = sorted(
            p for p in self.directory.iterdir() if p.suffix.lower() in (".jpg", ".jpeg")
        )
        self._load_images(images)

    def _load_images(self, images: list[Path]) -> None:
        self._populating = True
        self.rows = [RowState(path=p) for p in images]
        self.table.setRowCount(len(images))

        for row, path in enumerate(images):
            # read_metadata() is the single "master" place MetaJot's own
            # writer keeps IPTC/EXIF/XMP in sync through, so reopening a
            # processed folder shows exactly what was last written, however
            # it was written (title/description/keywords/location all come
            # from IPTC; the metajot:ProcessedAt marker comes from XMP).
            existing_meta = read_metadata(path)
            state = self.rows[row]
            state.current_meta = existing_meta
            state.processed = bool(existing_meta.processed_at)

            thumb_label = QLabel()
            thumb_label.setPixmap(load_thumbnail(path))
            self.table.setCellWidget(row, COL_THUMB, thumb_label)
            self.table.setItem(row, COL_FILENAME, self._readonly_item(path.name))
            title_item = QTableWidgetItem(existing_meta.title or "")
            self.table.setItem(row, COL_TITLE, title_item)
            desc_item = QTableWidgetItem(existing_meta.description or "")
            self.table.setItem(row, COL_DESCRIPTION, desc_item)
            keywords_item = QTableWidgetItem(", ".join(existing_meta.keywords))
            self.table.setItem(row, COL_KEYWORDS, keywords_item)

            # Shows the embedded location, or one reverse-geocoded from GPS
            # if there's none yet - the latter gets saved into the file on
            # the next write.
            self._set_location_cells(
                row, resolve_deterministic_location(existing_meta)
            )

            adobe_combo = self._make_adobe_combo(row)
            adobe_id = existing_meta.adobe_category_id or ""
            adobe_name = ADOBE_CATEGORY_NAMES_BY_ID.get(adobe_id)
            if adobe_name:
                adobe_combo.setCurrentText(adobe_name)
            self.table.setCellWidget(row, COL_ADOBE_CATEGORY, adobe_combo)

            primary_combo = self._make_shutter_combo(row)
            secondary_combo = self._make_shutter_combo(row, allow_none=True)
            categories = existing_meta.shutterstock_categories
            if categories:
                primary_combo.setCurrentText(categories[0])
            if len(categories) > 1:
                secondary_combo.setCurrentText(categories[1])
            self.table.setCellWidget(row, COL_SHUTTER_PRIMARY, primary_combo)
            self.table.setCellWidget(row, COL_SHUTTER_SECONDARY, secondary_combo)

            editorial_checkbox = self._make_editorial_checkbox()
            self.table.setCellWidget(row, COL_EDITORIAL, editorial_checkbox)

            status = "Done" if state.processed else "Pending"
            self.table.setItem(row, COL_STATUS, self._readonly_item(status))

        self._populating = False
        self._update_buttons()

    def _set_location_cells(self, row: int, location: Optional[Location]) -> None:
        location = location or Location()
        for col, value in (
            (COL_CITY, location.city),
            (COL_STATE, location.province_state),
            (COL_COUNTRY, location.country),
        ):
            self.table.setItem(row, col, QTableWidgetItem(value or ""))

    def _row_location(self, row: int) -> Location:
        return Location(
            city=self._cell_text(row, COL_CITY) or None,
            province_state=self._cell_text(row, COL_STATE) or None,
            country=self._cell_text(row, COL_COUNTRY) or None,
        )

    def _cell_text(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        return item.text().strip() if item else ""

    def _row_keywords(self, row: int) -> list[str]:
        keywords = self._cell_text(row, COL_KEYWORDS).split(",")
        return [k.strip() for k in keywords if k.strip()]

    def _set_status(self, row: int, text: str) -> None:
        self.table.item(row, COL_STATUS).setText(text)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() in EDITABLE_TEXT_COLUMNS:
            self._mark_dirty(item.row())

    def _mark_dirty(self, row: int) -> None:
        if self._populating or row >= len(self.rows):
            return
        self.rows[row].dirty = True
        self._set_status(row, "Modified")
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        self.process_btn.setEnabled(bool(self.rows) and not busy)
        self.write_btn.setEnabled(any(r.dirty for r in self.rows) and not busy)
        self.export_btn.setEnabled(any(r.processed for r in self.rows) and not busy)

    @staticmethod
    def _readonly_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _make_adobe_combo(self, row: int) -> QComboBox:
        combo = QComboBox()
        combo.addItems([c.value for c in AdobeStockCategory])
        combo.currentIndexChanged.connect(lambda _=None, r=row: self._mark_dirty(r))
        return combo

    def _make_shutter_combo(self, row: int, allow_none: bool = False) -> QComboBox:
        combo = QComboBox()
        if allow_none:
            combo.addItem(NO_SECONDARY)
        combo.addItems([c.value for c in ShutterstockCategory])
        combo.currentIndexChanged.connect(lambda _=None, r=row: self._mark_dirty(r))
        return combo

    @staticmethod
    def _make_editorial_checkbox() -> QCheckBox:
        checkbox = QCheckBox()
        checkbox.setToolTip(
            "Format the Shutterstock description as an editorial dateline "
            '("City, State/Country - Month Day Year: Description") for '
            "this photo when exporting CSVs."
        )
        return checkbox

    def start_processing(self) -> None:
        if not self.rows:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self.rows))
        self.progress.setValue(0)

        self.worker = ProcessingWorker([r.path for r in self.rows])
        self.worker.image_started.connect(self._on_image_started)
        self.worker.image_done.connect(self._on_image_done)
        self.worker.image_failed.connect(self._on_image_failed)
        self.worker.finished_all.connect(self._on_all_done)
        self._update_buttons()
        self.worker.start()

    def _on_image_started(self, row: int) -> None:
        self._set_status(row, "Processing...")

    def _on_image_done(
        self, row: int, current_meta: ImageMetadata, ai_data: AIResponse
    ) -> None:
        state = self.rows[row]
        state.current_meta = current_meta

        self._populating = True
        self.table.item(row, COL_TITLE).setText(ai_data.title)
        self.table.item(row, COL_DESCRIPTION).setText(ai_data.description)
        self.table.item(row, COL_KEYWORDS).setText(", ".join(ai_data.keywords))
        self._set_location_cells(
            row, resolve_location(current_meta, ai_data.location_guess())
        )

        adobe_combo: QComboBox = self.table.cellWidget(row, COL_ADOBE_CATEGORY)
        adobe_combo.setCurrentText(ai_data.adobe_category.value)

        primary_combo: QComboBox = self.table.cellWidget(row, COL_SHUTTER_PRIMARY)
        primary_combo.setCurrentText(ai_data.shutterstock_category_primary.value)

        secondary_combo: QComboBox = self.table.cellWidget(row, COL_SHUTTER_SECONDARY)
        secondary_value = ai_data.shutterstock_category_secondary
        secondary_combo.setCurrentText(
            secondary_value.value if secondary_value else NO_SECONDARY
        )
        self._populating = False

        state.processed = True
        state.dirty = True
        self._set_status(row, "Generated (unsaved)")
        self.progress.setValue(self.progress.value() + 1)

    def _on_image_failed(self, row: int, message: str) -> None:
        self._set_status(row, f"Error: {message}")
        self.progress.setValue(self.progress.value() + 1)

    def _on_all_done(self) -> None:
        self.progress.setVisible(False)
        self.worker = None
        self._update_buttons()

    def _row_categories(self, row: int) -> tuple[str, list[str]]:
        adobe_combo: QComboBox = self.table.cellWidget(row, COL_ADOBE_CATEGORY)
        adobe_category_id = str(ADOBE_CATEGORY_IDS[adobe_combo.currentText()])

        primary_combo: QComboBox = self.table.cellWidget(row, COL_SHUTTER_PRIMARY)
        secondary_combo: QComboBox = self.table.cellWidget(row, COL_SHUTTER_SECONDARY)
        shutterstock_categories = [primary_combo.currentText()]
        if secondary_combo.currentText() != NO_SECONDARY:
            shutterstock_categories.append(secondary_combo.currentText())
        return adobe_category_id, shutterstock_categories

    def _write_dirty_rows(self) -> tuple[int, list[str]]:
        """Writes every modified row into its file; returns (written count,
        failed filenames)."""
        written = 0
        failures: list[str] = []
        for row, state in enumerate(self.rows):
            if not state.dirty:
                continue
            adobe_category_id, shutterstock_categories = self._row_categories(row)
            location = self._row_location(row)
            success = write_metadata(
                state.path,
                self._cell_text(row, COL_TITLE),
                self._cell_text(row, COL_DESCRIPTION),
                self._row_keywords(row),
                adobe_category_id,
                shutterstock_categories,
                location=location,
            )
            if success:
                written += 1
                state.dirty = False
                state.processed = True
                if state.current_meta and not location.is_empty():
                    state.current_meta.iptc_city = location.city
                    state.current_meta.iptc_province_state = location.province_state
                    state.current_meta.iptc_country = location.country
                self._set_status(row, "Written")
            else:
                failures.append(state.path.name)
                self._set_status(row, "Write failed")
        self._update_buttons()
        return written, failures

    def write_metadata_clicked(self) -> None:
        written, failures = self._write_dirty_rows()
        if failures:
            QMessageBox.warning(
                self,
                "Some files failed",
                "Failed to write metadata for:\n" + "\n".join(failures),
            )
        else:
            QMessageBox.information(
                self, "Done", f"Wrote metadata to {written} image(s)."
            )

    def export_csvs(self) -> None:
        if not self.directory:
            return

        unsaved = sum(1 for r in self.rows if r.dirty)
        if unsaved:
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                f"{unsaved} photo(s) have changes not yet written to the "
                "files. Write them before exporting?\n\n"
                "(Choosing No exports the table as shown, without saving it "
                "into the photos.)",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                _, failures = self._write_dirty_rows()
                if failures:
                    QMessageBox.warning(
                        self,
                        "Some files failed",
                        "Failed to write metadata for:\n"
                        + "\n".join(failures)
                        + "\n\nCSVs were not exported.",
                    )
                    return

        records: list[ExportRecord] = []
        editorial_unresolved: list[str] = []

        for row, state in enumerate(self.rows):
            if not state.processed:
                continue

            description = self._cell_text(row, COL_DESCRIPTION)
            adobe_category_id, shutterstock_categories = self._row_categories(row)

            editorial_checkbox: QCheckBox = self.table.cellWidget(row, COL_EDITORIAL)
            editorial_requested = editorial_checkbox.isChecked()
            location = self._row_location(row)
            meta = state.current_meta or ImageMetadata()
            date_created = meta.date_created
            shutterstock_description = build_shutterstock_description(
                description, location, date_created, editorial_requested
            )
            # Only mark the CSV row Editorial if a dateline was actually
            # resolved and applied above - marking it Yes without one would
            # get the submission rejected by Shutterstock.
            dateline_applied = editorial_requested and resolve_editorial_dateline(
                location, date_created
            )
            if editorial_requested and not dateline_applied:
                editorial_unresolved.append(state.path.name)

            records.append(
                ExportRecord(
                    filename=state.path.name,
                    title=self._cell_text(row, COL_TITLE),
                    description=shutterstock_description,
                    keywords=self._row_keywords(row),
                    adobe_category_id=adobe_category_id,
                    shutterstock_categories=shutterstock_categories,
                    editorial=bool(dateline_applied),
                )
            )

        export_adobe_stock_csv(records, self.directory / "adobe_stock.csv")
        export_shutterstock_csv(records, self.directory / "shutterstock.csv")

        if editorial_unresolved:
            QMessageBox.warning(
                self,
                "Editorial dateline not applied",
                "No location or date could be resolved for the following "
                "photos, so they were exported without the editorial "
                "dateline:\n" + "\n".join(editorial_unresolved),
            )
        else:
            QMessageBox.information(
                self, "Done", f"Exported CSVs for {len(records)} image(s)."
            )
