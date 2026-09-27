from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    AIResponse,
    build_shutterstock_description,
    resolve_editorial_dateline,
    resolve_location,
)
from metajot.exporter import (
    ExportRecord,
    export_adobe_stock_csv,
    export_shutterstock_csv,
)
from metajot.gui.detail_dialog import DetailDialog
from metajot.gui.row_state import RowState, load_thumbnail
from metajot.gui.worker import ProcessingWorker
from metajot.metadata import (
    ImageMetadata,
    read_metadata,
    resolve_deterministic_location,
    write_metadata,
)

THUMBNAIL_SIZE = 192

COL_THUMB = 0
COL_FILENAME = 1
COL_TITLE = 2
COL_EDITORIAL = 3
COL_STATUS = 4
COLUMN_COUNT = 5

COLUMN_HEADERS = ["", "Filename", "Title", "Editorial", "Status"]

# Index into MainWindow.rows, stored on each row's filename item so a table
# row can be mapped back to its RowState whatever the current sort order.
ROW_INDEX_ROLE = Qt.ItemDataRole.UserRole
# Explicit sort key for items whose display text isn't what should be sorted
# on (the thumbnail, which has none).
SORT_KEY_ROLE = Qt.ItemDataRole.UserRole + 1

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL_MS = 80


class SortableItem(QTableWidgetItem):
    """Sorts case-insensitively by text, by check state for checkbox items,
    or by an explicit SORT_KEY_ROLE value if set."""

    def _sort_key(self):
        # Not flags() & ItemIsUserCheckable: that flag is on by default for
        # every item, whereas only real checkbox items have a check state.
        if self.data(Qt.ItemDataRole.CheckStateRole) is not None:
            return self.checkState().value
        key = self.data(SORT_KEY_ROLE)
        return key if key is not None else self.text().lower()

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortableItem):
            return self._sort_key() < other._sort_key()
        return super().__lt__(other)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MetaJot")
        self.resize(1100, 800)

        self.directory: Optional[Path] = None
        self.rows: list[RowState] = []
        self.worker: Optional[ProcessingWorker] = None
        self._processed_count = 0
        self._spinner_frame = 0
        self._activity_text = ""

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        self.select_btn = QPushButton("Select Folder...")
        self.select_btn.clicked.connect(self.select_folder)
        self.folder_label = QLabel("No folder selected")
        self.process_btn = QPushButton("Process with AI")
        self.process_btn.clicked.connect(self.start_processing)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop after the photo currently being processed.")
        self.cancel_btn.clicked.connect(self.cancel_processing)
        self.cancel_btn.setVisible(False)
        self.write_btn = QPushButton("Write Metadata")
        self.write_btn.setToolTip(
            "Save the generated title, description, keywords, location and "
            "categories into the photo files."
        )
        self.write_btn.clicked.connect(self.write_metadata_clicked)
        self.export_btn = QPushButton("Export CSVs")
        self.export_btn.setToolTip(
            "Write adobe_stock.csv and shutterstock.csv for all processed "
            "photos in this folder."
        )
        self.export_btn.clicked.connect(self.export_csvs)
        top_bar.addWidget(self.select_btn)
        top_bar.addWidget(self.folder_label, 1)
        top_bar.addWidget(self.process_btn)
        top_bar.addWidget(self.cancel_btn)
        top_bar.addWidget(self.write_btn)
        top_bar.addWidget(self.export_btn)
        layout.addLayout(top_bar)

        activity_bar = QHBoxLayout()
        self.activity_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        activity_bar.addWidget(self.activity_label, 1)
        activity_bar.addWidget(self.progress, 1)
        layout.addLayout(activity_bar)
        self.activity_label.setVisible(False)
        self.progress.setVisible(False)

        self.spinner_timer = QTimer(self)
        self.spinner_timer.setInterval(SPINNER_INTERVAL_MS)
        self.spinner_timer.timeout.connect(self._advance_spinner)

        self.table = QTableWidget(0, COLUMN_COUNT)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(THUMBNAIL_SIZE + 8)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_THUMB, THUMBNAIL_SIZE + 8)
        self.table.setColumnWidth(COL_FILENAME, 220)
        self.table.setColumnWidth(COL_EDITORIAL, 80)
        self.table.setColumnWidth(COL_STATUS, 160)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(
            lambda row, _col: self._open_details(row)
        )
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
        # Rows must be inserted unsorted, or they'd move while being filled.
        self.table.setSortingEnabled(False)
        self.rows = []
        self.table.setRowCount(len(images))

        for index, path in enumerate(images):
            # read_metadata() is the single "master" place MetaJot's own
            # writer keeps IPTC/EXIF/XMP in sync through, so reopening a
            # processed folder shows exactly what was last written, however
            # it was written (title/description/keywords/location all come
            # from IPTC; the metajot:ProcessedAt marker comes from XMP).
            meta = read_metadata(path)
            state = RowState(
                path=path,
                current_meta=meta,
                title=meta.title or "",
                description=meta.description or "",
                keywords=list(meta.keywords),
                # The embedded location, or one reverse-geocoded from GPS if
                # there's none yet - the latter gets saved on the next write.
                location=resolve_deterministic_location(meta),
                adobe_category_id=meta.adobe_category_id,
                shutterstock_categories=list(meta.shutterstock_categories),
                processed=bool(meta.processed_at),
                status="Done" if meta.processed_at else "Pending",
            )
            self.rows.append(state)

            thumb_item = SortableItem()
            thumb_item.setData(
                Qt.ItemDataRole.DecorationRole, load_thumbnail(path, THUMBNAIL_SIZE)
            )
            thumb_item.setData(SORT_KEY_ROLE, path.name.lower())
            thumb_item.setToolTip("Click to view details")
            self.table.setItem(index, COL_THUMB, thumb_item)

            filename_item = SortableItem(path.name)
            filename_item.setData(ROW_INDEX_ROLE, index)
            self.table.setItem(index, COL_FILENAME, filename_item)

            state.title_item = SortableItem(state.title)
            state.title_item.setToolTip(state.title)
            self.table.setItem(index, COL_TITLE, state.title_item)

            state.editorial_item = SortableItem()
            state.editorial_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            state.editorial_item.setCheckState(Qt.CheckState.Unchecked)
            state.editorial_item.setToolTip(
                "Format the Shutterstock description as an editorial dateline "
                '("City, State/Country - Month Day Year: Description") for '
                "this photo when exporting CSVs."
            )
            self.table.setItem(index, COL_EDITORIAL, state.editorial_item)

            state.status_item = SortableItem(state.status)
            self.table.setItem(index, COL_STATUS, state.status_item)

        self.table.setSortingEnabled(True)
        self.table.sortItems(COL_FILENAME, Qt.SortOrder.AscendingOrder)
        self._update_buttons()

    def _state_at(self, table_row: int) -> Optional[RowState]:
        item = self.table.item(table_row, COL_FILENAME)
        if item is None:
            return None
        return self.rows[item.data(ROW_INDEX_ROLE)]

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col == COL_THUMB:
            self._open_details(row)

    def _open_details(self, table_row: int) -> None:
        state = self._state_at(table_row)
        if state:
            DetailDialog(state, self).exec()

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        self.select_btn.setEnabled(not busy)
        self.process_btn.setEnabled(bool(self.rows) and not busy)
        self.cancel_btn.setVisible(busy)
        self.write_btn.setEnabled(any(r.dirty for r in self.rows) and not busy)
        self.export_btn.setEnabled(any(r.processed for r in self.rows) and not busy)

    def _set_activity(self, text: str) -> None:
        self._activity_text = text
        self._render_activity()

    def _render_activity(self) -> None:
        spinner = SPINNER_FRAMES[self._spinner_frame]
        self.activity_label.setText(f"{spinner}  {self._activity_text}")

    def _advance_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
        self._render_activity()

    def start_processing(self) -> None:
        if not self.rows:
            return
        self._processed_count = 0
        self.progress.setRange(0, len(self.rows))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.activity_label.setVisible(True)
        self._set_activity("Starting...")
        self.spinner_timer.start()

        self.worker = ProcessingWorker([r.path for r in self.rows])
        self.worker.image_started.connect(self._on_image_started)
        self.worker.image_done.connect(self._on_image_done)
        self.worker.image_failed.connect(self._on_image_failed)
        self.worker.finished_all.connect(self._on_all_done)
        self._update_buttons()
        self.worker.start()

    def cancel_processing(self) -> None:
        if not self.worker:
            return
        self.worker.stop()
        self.cancel_btn.setEnabled(False)
        self._set_activity("Cancelling after the current photo...")

    def _on_image_started(self, index: int) -> None:
        state = self.rows[index]
        state.set_status("Processing...")
        if self.cancel_btn.isEnabled():
            self._set_activity(
                f"Processing {index + 1} of {len(self.rows)}: {state.path.name}"
            )

    def _on_image_done(
        self, index: int, current_meta: ImageMetadata, ai_data: AIResponse
    ) -> None:
        state = self.rows[index]
        state.current_meta = current_meta
        state.set_title(ai_data.title)
        state.title_item.setToolTip(ai_data.title)
        state.description = ai_data.description
        state.keywords = list(ai_data.keywords)
        state.location = resolve_location(current_meta, ai_data.location_guess())
        state.adobe_category_id = str(ADOBE_CATEGORY_IDS[ai_data.adobe_category.value])
        state.shutterstock_categories = [ai_data.shutterstock_category_primary.value]
        if ai_data.shutterstock_category_secondary:
            state.shutterstock_categories.append(
                ai_data.shutterstock_category_secondary.value
            )
        state.processed = True
        state.dirty = True
        state.set_status("Generated (unsaved)")
        self._step_progress()

    def _on_image_failed(self, index: int, message: str) -> None:
        self.rows[index].set_status(f"Error: {message}")
        self._step_progress()

    def _step_progress(self) -> None:
        self._processed_count += 1
        self.progress.setValue(self._processed_count)

    def _on_all_done(self) -> None:
        cancelled = self.worker is not None and self.worker.stop_requested
        self.worker = None
        self.spinner_timer.stop()
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.activity_label.setVisible(False)
        self._update_buttons()
        if cancelled:
            QMessageBox.information(
                self,
                "Cancelled",
                f"Processing cancelled after {self._processed_count} of "
                f"{len(self.rows)} photo(s).",
            )

    def closeEvent(self, event) -> None:
        # Let the worker finish its current photo rather than killing the
        # thread mid-write/mid-request.
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        super().closeEvent(event)

    def _write_dirty_rows(self) -> tuple[int, list[str]]:
        """Writes every row with unsaved generated metadata into its file;
        returns (written count, failed filenames)."""
        written = 0
        failures: list[str] = []
        for state in self.rows:
            if not state.dirty:
                continue
            success = write_metadata(
                state.path,
                state.title,
                state.description,
                state.keywords,
                state.adobe_category_id,
                state.shutterstock_categories,
                location=state.location,
            )
            if success:
                written += 1
                state.dirty = False
                state.processed = True
                state.set_status("Written")
            else:
                failures.append(state.path.name)
                state.set_status("Write failed")
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
                f"{unsaved} photo(s) have generated metadata not yet written "
                "to the files. Write them before exporting?\n\n"
                "(Choosing No exports it anyway, without saving it into the "
                "photos.)",
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

        for state in sorted(self.rows, key=lambda r: r.path.name.lower()):
            if not state.processed:
                continue

            meta = state.current_meta or ImageMetadata()
            date_created = meta.date_created
            shutterstock_description = build_shutterstock_description(
                state.description, state.location, date_created, state.editorial
            )
            # Only mark the CSV row Editorial if a dateline was actually
            # resolved and applied above - marking it Yes without one would
            # get the submission rejected by Shutterstock.
            dateline_applied = state.editorial and resolve_editorial_dateline(
                state.location, date_created
            )
            if state.editorial and not dateline_applied:
                editorial_unresolved.append(state.path.name)

            records.append(
                ExportRecord(
                    filename=state.path.name,
                    title=state.title,
                    description=shutterstock_description,
                    keywords=state.keywords,
                    adobe_category_id=state.adobe_category_id or "",
                    shutterstock_categories=state.shutterstock_categories,
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
