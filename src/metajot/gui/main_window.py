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
from metajot.gui.widgets import (
    SORT_KEY_ROLE,
    CheckableHeader,
    PhotoDelegate,
    SortableItem,
)
from metajot.gui.worker import ProcessingWorker
from metajot.metadata import (
    ImageMetadata,
    read_metadata,
    resolve_deterministic_location,
    write_editorial_flag,
    write_metadata,
)

THUMBNAIL_SIZE = 192

COL_PROCESS = 0
COL_PHOTO = 1
COL_TITLE = 2
COL_EDITORIAL = 3
COL_STATUS = 4
COLUMN_COUNT = 5

COLUMN_HEADERS = ["Process", "Photo", "Title", "Editorial", "Status"]
CHECKBOX_COLUMNS = (COL_PROCESS, COL_EDITORIAL)

PROCESS_TOOLTIP = "Include this photo in the next \"Process with AI\" run."
EDITORIAL_TOOLTIP = (
    "Editorial use: formats the Shutterstock description as an editorial "
    'dateline ("City, State/Country - Month Day Year: Description") when '
    "exporting CSVs. Saved in the photo by Write Metadata."
)

# Index into MainWindow.rows, stored on each row's photo item so a table row
# can be mapped back to its RowState whatever the current sort order.
ROW_INDEX_ROLE = Qt.ItemDataRole.UserRole

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_INTERVAL_MS = 80

STATUS_GENERATED = "Generated (unsaved)"
STATUS_EDITORIAL_CHANGED = "Editorial changed (unsaved)"


def _checkbox_item(checked: bool, tooltip: str) -> SortableItem:
    item = SortableItem()
    item.setFlags(
        Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsUserCheckable
    )
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    item.setToolTip(tooltip)
    return item


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MetaJot")
        self.resize(1000, 800)

        self.directory: Optional[Path] = None
        self.rows: list[RowState] = []
        self.worker: Optional[ProcessingWorker] = None
        self._job_count = 0
        self._started_count = 0
        self._finished_count = 0
        self._spinner_frame = 0
        self._activity_text = ""
        # Set while items are created/filled programmatically, so their
        # itemChanged signals aren't taken as user changes.
        self._populating = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        self.select_btn = QPushButton("Select Folder...")
        self.select_btn.clicked.connect(self.select_folder)
        self.folder_label = QLabel("No folder selected")
        self.process_btn = QPushButton("Process with AI")
        self.process_btn.setToolTip(
            "Generate metadata for the photos ticked in the Process column."
        )
        self.process_btn.clicked.connect(self.start_processing)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop after the photo currently being processed.")
        self.cancel_btn.clicked.connect(self.cancel_processing)
        self.cancel_btn.setVisible(False)
        self.write_btn = QPushButton("Write Metadata")
        self.write_btn.setToolTip(
            "Save the generated title, description, keywords, location and "
            "categories, and the Editorial flag, into the photo files."
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
        self.header = CheckableHeader(self.table)
        self.table.setHorizontalHeader(self.header)
        self.table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self.table.horizontalHeaderItem(COL_PROCESS).setToolTip(
            "Tick the box to select/deselect all. " + PROCESS_TOOLTIP
        )
        self.table.horizontalHeaderItem(COL_EDITORIAL).setToolTip(
            "Tick the box to select/deselect all. " + EDITORIAL_TOOLTIP
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.table.setItemDelegateForColumn(COL_PHOTO, PhotoDelegate(self.table))
        self.table.verticalHeader().setVisible(False)
        # Fits each row to its thumbnail + filename, so landscape photos
        # don't get a portrait-height row.
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        for column in CHECKBOX_COLUMNS:
            # Keeps the label clear of the check-all box drawn at the left.
            self.table.horizontalHeaderItem(column).setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        self.header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_PROCESS, 100)
        self.table.setColumnWidth(COL_PHOTO, THUMBNAIL_SIZE + 16)
        self.table.setColumnWidth(COL_EDITORIAL, 100)
        self.table.setColumnWidth(COL_STATUS, 180)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        self.header.toggled.connect(self._toggle_all)
        layout.addWidget(self.table)

        self._refresh_header_checks()
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
        # Rows must be inserted unsorted, or they'd move while being filled.
        self.table.setSortingEnabled(False)
        self.rows = []
        self.table.setRowCount(len(images))

        for index, path in enumerate(images):
            # read_metadata() is the single "master" place MetaJot's own
            # writer keeps IPTC/EXIF/XMP in sync through, so reopening a
            # processed folder shows exactly what was last written, however
            # it was written (title/description/keywords/location all come
            # from IPTC; the metajot:ProcessedAt/Editorial flags from XMP).
            meta = read_metadata(path)
            processed = bool(meta.processed_at)
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
                processed=processed,
                saved_editorial=meta.editorial,
                clean_status="Done" if processed else "Pending",
            )
            self.rows.append(state)

            # Unprocessed photos are pre-selected for the next AI run.
            state.process_item = _checkbox_item(not processed, PROCESS_TOOLTIP)
            self.table.setItem(index, COL_PROCESS, state.process_item)

            photo_item = SortableItem(path.name)
            photo_item.setData(
                Qt.ItemDataRole.DecorationRole, load_thumbnail(path, THUMBNAIL_SIZE)
            )
            photo_item.setData(SORT_KEY_ROLE, path.name.lower())
            photo_item.setData(ROW_INDEX_ROLE, index)
            photo_item.setToolTip("Click the thumbnail to view details")
            self.table.setItem(index, COL_PHOTO, photo_item)

            state.title_item = SortableItem(state.title)
            state.title_item.setToolTip(state.title)
            self.table.setItem(index, COL_TITLE, state.title_item)

            state.editorial_item = _checkbox_item(meta.editorial, EDITORIAL_TOOLTIP)
            self.table.setItem(index, COL_EDITORIAL, state.editorial_item)

            state.status_item = SortableItem(state.clean_status)
            self.table.setItem(index, COL_STATUS, state.status_item)
            state.status = state.clean_status

        self.table.setSortingEnabled(True)
        self.table.sortItems(COL_PHOTO, Qt.SortOrder.AscendingOrder)
        self._populating = False
        self._refresh_header_checks()
        self._update_buttons()

    def _state_at(self, table_row: int) -> Optional[RowState]:
        item = self.table.item(table_row, COL_PHOTO)
        if item is None:
            return None
        return self.rows[item.data(ROW_INDEX_ROLE)]

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col == COL_PHOTO:
            self._open_details(row)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        # Double-clicking a checkbox cell would otherwise both toggle it and
        # open the dialog; the photo column already opens it on one click.
        if col not in CHECKBOX_COLUMNS and col != COL_PHOTO:
            self._open_details(row)

    def _open_details(self, table_row: int) -> None:
        state = self._state_at(table_row)
        if state:
            DetailDialog(state, self).exec()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or item.column() not in CHECKBOX_COLUMNS:
            return
        if item.column() == COL_EDITORIAL:
            state = self._state_at(item.row())
            if state:
                self._refresh_status(state)
        self._refresh_header_checks()
        self._update_buttons()

    def _toggle_all(self, column: int) -> None:
        items = [self.table.item(row, column) for row in range(self.table.rowCount())]
        all_checked = bool(items) and all(
            i.checkState() == Qt.CheckState.Checked for i in items
        )
        new_state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        # Items are collected up front: with the table sorted by this column,
        # each change re-sorts it, so re-reading item(row, ...) mid-loop
        # would skip or repeat rows.
        for item in items:
            item.setCheckState(new_state)

    def _refresh_header_checks(self) -> None:
        for column in CHECKBOX_COLUMNS:
            checked = sum(
                1
                for row in range(self.table.rowCount())
                if self.table.item(row, column).checkState() == Qt.CheckState.Checked
            )
            if checked == 0:
                state = Qt.CheckState.Unchecked
            elif checked == self.table.rowCount():
                state = Qt.CheckState.Checked
            else:
                state = Qt.CheckState.PartiallyChecked
            self.header.set_check_state(column, state)

    def _refresh_status(self, state: RowState) -> None:
        if state.dirty:
            state.set_status(STATUS_GENERATED)
        elif state.editorial_changed:
            state.set_status(STATUS_EDITORIAL_CHANGED)
        else:
            state.set_status(state.clean_status)

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        selected = sum(1 for r in self.rows if r.selected_for_processing)
        self.process_btn.setText(
            f"Process with AI ({selected})" if selected else "Process with AI"
        )
        self.select_btn.setEnabled(not busy)
        self.process_btn.setEnabled(selected > 0 and not busy)
        self.cancel_btn.setVisible(busy)
        self.write_btn.setEnabled(
            any(r.has_unsaved_changes for r in self.rows) and not busy
        )
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
        # Process in the order currently shown in the table.
        jobs = []
        for row in range(self.table.rowCount()):
            index = self.table.item(row, COL_PHOTO).data(ROW_INDEX_ROLE)
            state = self.rows[index]
            if state.selected_for_processing:
                jobs.append((index, state.path))
        if not jobs:
            return

        self._job_count = len(jobs)
        self._started_count = 0
        self._finished_count = 0
        self.progress.setRange(0, self._job_count)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.activity_label.setVisible(True)
        self._set_activity("Starting...")
        self.spinner_timer.start()

        self.worker = ProcessingWorker(jobs)
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
        self._started_count += 1
        if self.cancel_btn.isEnabled():
            self._set_activity(
                f"Processing {self._started_count} of {self._job_count}: "
                f"{state.path.name}"
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
        self._refresh_status(state)
        # Done - a re-run shouldn't redo it unless it's ticked again.
        state.set_selected_for_processing(False)
        self._step_progress()

    def _on_image_failed(self, index: int, message: str) -> None:
        self.rows[index].set_status(f"Error: {message}")
        self._step_progress()

    def _step_progress(self) -> None:
        self._finished_count += 1
        self.progress.setValue(self._finished_count)

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
                f"Processing cancelled after {self._finished_count} of "
                f"{self._job_count} photo(s).",
            )

    def closeEvent(self, event) -> None:
        # Let the worker finish its current photo rather than killing the
        # thread mid-write/mid-request.
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        super().closeEvent(event)

    def _write_unsaved_rows(self) -> tuple[int, list[str]]:
        """Writes every row with unsaved changes into its file; returns
        (written count, failed filenames)."""
        written = 0
        failures: list[str] = []
        for state in self.rows:
            if state.dirty:
                success = write_metadata(
                    state.path,
                    state.title,
                    state.description,
                    state.keywords,
                    state.adobe_category_id,
                    state.shutterstock_categories,
                    location=state.location,
                    editorial=state.editorial,
                )
            elif state.editorial_changed:
                # Only the flag changed - don't rewrite (or, for a photo
                # never processed, stamp as processed) everything else.
                success = write_editorial_flag(state.path, state.editorial)
            else:
                continue

            if success:
                written += 1
                if state.dirty:
                    state.clean_status = "Written"
                state.dirty = False
                state.saved_editorial = state.editorial
                self._refresh_status(state)
            else:
                failures.append(state.path.name)
                state.set_status("Write failed")
        self._update_buttons()
        return written, failures

    def write_metadata_clicked(self) -> None:
        written, failures = self._write_unsaved_rows()
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

        unsaved = sum(1 for r in self.rows if r.has_unsaved_changes)
        if unsaved:
            answer = QMessageBox.question(
                self,
                "Unsaved changes",
                f"{unsaved} photo(s) have changes not yet written to the "
                "files. Write them before exporting?\n\n"
                "(Choosing No exports them anyway, without saving them into "
                "the photos.)",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                _, failures = self._write_unsaved_rows()
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
