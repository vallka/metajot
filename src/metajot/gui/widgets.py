from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QTableWidgetItem,
)

# Explicit sort key for items whose display text isn't what should be sorted
# on.
SORT_KEY_ROLE = Qt.ItemDataRole.UserRole + 1

# Left inset of the header checkbox, roughly lining it up with the item
# checkboxes in the column below it.
HEADER_CHECKBOX_INSET = 4


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


class CheckableHeader(QHeaderView):
    """Horizontal header that draws a check-all checkbox in chosen sections.
    Clicking the checkbox emits toggled(section) instead of sorting;
    clicking elsewhere in the section still sorts as usual."""

    toggled = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self._states: dict[int, Qt.CheckState] = {}
        self._swallow_release = False

    def set_check_state(self, section: int, state: Qt.CheckState) -> None:
        if self._states.get(section) != state:
            self._states[section] = state
            self.viewport().update()

    def _checkbox_rect(self, section: int) -> QRect:
        style = self.style()
        width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
        height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight)
        x = self.sectionViewportPosition(section) + HEADER_CHECKBOX_INSET
        y = (self.height() - height) // 2
        return QRect(x, y, width, height)

    def paintSection(self, painter, rect, logical_index) -> None:
        painter.save()
        super().paintSection(painter, rect, logical_index)
        painter.restore()

        state = self._states.get(logical_index)
        if state is None:
            return
        option = QStyleOptionButton()
        option.rect = self._checkbox_rect(logical_index)
        option.state = QStyle.StateFlag.State_Enabled
        if state == Qt.CheckState.Checked:
            option.state |= QStyle.StateFlag.State_On
        elif state == Qt.CheckState.PartiallyChecked:
            option.state |= QStyle.StateFlag.State_NoChange
        else:
            option.state |= QStyle.StateFlag.State_Off
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorCheckBox, option, painter
        )

    def _checkbox_at(self, pos) -> int:
        section = self.logicalIndexAt(pos)
        if section in self._states and self._checkbox_rect(section).contains(pos):
            return section
        return -1

    def mousePressEvent(self, event) -> None:
        section = self._checkbox_at(event.position().toPoint())
        if section >= 0:
            self._swallow_release = True
            self.toggled.emit(section)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        # The release belonging to a checkbox click mustn't reach
        # QHeaderView, or it could still be taken as a sort click.
        if self._swallow_release:
            self._swallow_release = False
            return
        super().mouseReleaseEvent(event)


class PhotoDelegate(QStyledItemDelegate):
    """Draws the photo column's thumbnail with the filename centred below."""

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        option.decorationPosition = QStyleOptionViewItem.Position.Top
        option.decorationAlignment = Qt.AlignmentFlag.AlignHCenter
        option.displayAlignment = (
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
