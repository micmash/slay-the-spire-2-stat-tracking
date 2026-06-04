"""Reusable Qt helpers: labels, sortable table items, filter combos, table IO."""
import csv
from typing import Callable

from PyQt6.QtWidgets import (
    QLabel, QPushButton, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QWidget, QVBoxLayout, QHBoxLayout, QProgressBar, QFileDialog, QMessageBox,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from theme import TEXT, MUTED, WIN_COLOR, LOSS_COLOR, ACCENT2, DARK_BG, CARD_BG, PANEL_BG

ALL_CHARACTERS = "All Characters"


class ModeFilterWidget(QWidget):
    """Three checkboxes — Singleplayer / Multiplayer / Daily — emitting changed() when toggled."""
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.cb_sp    = self._cb("SP",    layout)
        self.cb_mp    = self._cb("MP",    layout)
        self.cb_daily = self._cb("Daily", layout)

    def _cb(self, label: str, layout: QHBoxLayout) -> QCheckBox:
        cb = QCheckBox(label)
        cb.setChecked(True)
        cb.setStyleSheet(f"color: {TEXT}; spacing: 4px;")
        cb.checkStateChanged.connect(self.changed)
        layout.addWidget(cb)
        return cb

    # Convenience accessors matching filter_runs signature
    @property
    def include_sp(self) -> bool:    return self.cb_sp.isChecked()
    @property
    def include_mp(self) -> bool:    return self.cb_mp.isChecked()
    @property
    def include_daily(self) -> bool: return self.cb_daily.isChecked()


# ── Labels ───────────────────────────────────────────────────────────
def make_label(text: str, bold: bool = False, size: int = 13, color: str = TEXT) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPointSize(size)
    font.setBold(bold)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color};")
    return lbl


# ── Sortable numeric table items ─────────────────────────────────────
class SortableItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by its UserRole value numerically."""
    def __lt__(self, other: QTableWidgetItem) -> bool:
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        try:
            return float(a) < float(b)
        except (TypeError, ValueError):
            return super().__lt__(other)


def wr_item(wr: float | None, n: int) -> SortableItem:
    """Win-rate cell: 'NN.N%  (n)', green if >=50%, '—' when no data."""
    if wr is None:
        item = SortableItem("—")
        item.setData(Qt.ItemDataRole.UserRole, -99.0)
        item.setForeground(QColor(MUTED))
    else:
        item = SortableItem(f"{wr*100:.1f}%  ({n})")
        item.setData(Qt.ItemDataRole.UserRole, wr)
        item.setForeground(QColor(WIN_COLOR if wr >= 0.5 else LOSS_COLOR))
    return item


def delta_item(delta: float | None) -> SortableItem:
    """Win-delta cell in percentage points; green/red beyond ±5pp."""
    if delta is None:
        item = SortableItem("—")
        item.setData(Qt.ItemDataRole.UserRole, -99.0)
        item.setForeground(QColor(MUTED))
        return item
    sign = "+" if delta > 0 else ""
    item = SortableItem(f"{sign}{delta*100:.1f}pp")
    item.setData(Qt.ItemDataRole.UserRole, delta)
    if delta > 0.05:
        item.setForeground(QColor(WIN_COLOR))
    elif delta < -0.05:
        item.setForeground(QColor(LOSS_COLOR))
    else:
        item.setForeground(QColor(MUTED))
    return item


def pct_item(rate: float) -> SortableItem:
    """Plain percentage cell, green if >=50%."""
    item = SortableItem(f"{rate*100:.1f}%")
    item.setData(Qt.ItemDataRole.UserRole, rate)
    item.setForeground(QColor(WIN_COLOR if rate >= 0.5 else LOSS_COLOR))
    return item


def num_item(value: int | float) -> SortableItem:
    """Numeric cell that sorts numerically."""
    item = SortableItem(str(value))
    item.setData(Qt.ItemDataRole.UserRole, float(value))
    return item


def make_mode_filter(on_change: Callable[[], None]) -> ModeFilterWidget:
    """Create a ModeFilterWidget wired to on_change."""
    w = ModeFilterWidget()
    w.changed.connect(on_change)
    return w


# ── Filter combo helpers (dedups the per-tab boilerplate) ────────────
def make_char_combo(on_change: Callable[[], None]) -> QComboBox:
    """Character filter combo seeded with the 'All Characters' option."""
    combo = QComboBox()
    combo.addItem(ALL_CHARACTERS)
    combo.currentTextChanged.connect(on_change)
    return combo


def populate_char_combo(combo: QComboBox, runs) -> None:
    """Refill a character combo from the run set, preserving the current pick."""
    chars = sorted({r.character_display for r in runs})
    current = combo.currentText()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(ALL_CHARACTERS)
    combo.addItems(chars)
    if current in chars:
        combo.setCurrentText(current)
    combo.blockSignals(False)


# ── Progress bar widget ──────────────────────────────────────────────
def bar_widget(value: float, color: str, label_left: str = "", label_right: str = "") -> QWidget:
    """A labeled horizontal progress bar for a 0–1 value."""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    if label_left or label_right:
        row = QHBoxLayout()
        row.addWidget(make_label(label_left, size=10, color=MUTED))
        row.addStretch()
        row.addWidget(make_label(label_right, size=10, color=color))
        layout.addLayout(row)
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(int(value * 100))
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setStyleSheet(
        f"QProgressBar {{ background: {DARK_BG}; border-radius: 4px; border: none; }}"
        f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
    )
    layout.addWidget(bar)
    return w


# ── Table population & export ────────────────────────────────────────
def repopulate_table(table: QTableWidget, populate_fn: Callable[[], None]) -> None:
    """
    Safely repopulate a QTableWidget:
    - blocks signals so selection changes mid-rebuild don't fire callbacks
    - disables sorting during population (avoids re-sort on every setItem)
    - saves & restores the user's sort indicator so filtering keeps the sort
    """
    hdr = table.horizontalHeader()
    sort_col = hdr.sortIndicatorSection()
    sort_order = hdr.sortIndicatorOrder()

    table.blockSignals(True)
    table.setSortingEnabled(False)
    table.clearContents()

    populate_fn()

    table.setSortingEnabled(True)
    if sort_col >= 0:
        table.sortByColumn(sort_col, sort_order)
    table.blockSignals(False)


def export_table_to_csv(table: QTableWidget, parent: QWidget | None = None) -> None:
    """Export the table's currently visible rows/columns to a CSV file."""
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export CSV", "", "CSV files (*.csv);;All files (*)"
    )
    if not path:
        return
    headers = [
        table.horizontalHeaderItem(c).text()
        for c in range(table.columnCount())
        if table.horizontalHeaderItem(c)
    ]
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in range(table.rowCount()):
                writer.writerow([
                    (table.item(row, col).text() if table.item(row, col) else "")
                    for col in range(table.columnCount())
                ])
    except OSError as e:
        QMessageBox.warning(parent, "Export failed", str(e))


def add_export_btn(layout: QHBoxLayout, table_getter: Callable[[], QTableWidget], parent: QWidget) -> QPushButton:
    """Append a wired-up 'Export CSV' button to a filter row."""
    btn = QPushButton("Export CSV")
    btn.setStyleSheet(f"background: {CARD_BG}; color: {TEXT}; border: none; padding: 5px 12px; border-radius: 4px;")
    btn.clicked.connect(lambda: export_table_to_csv(table_getter(), parent))
    layout.addWidget(btn)
    return btn
