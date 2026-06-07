"""Slay the Spire 2 — local run tracker. Entry point and UI tabs."""
import sys
from pathlib import Path
from collections import defaultdict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QLabel, QPushButton,
    QFileDialog, QTextEdit, QSplitter, QHeaderView, QComboBox,
    QLineEdit, QFrame, QScrollArea, QGridLayout, QStackedWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QFileSystemWatcher, QSettings
from PyQt6.QtGui import QColor, QPixmap
import ctypes

from parser import RunSummary, find_default_save_path, fmt_card, fmt_relic
from notes_store import load_notes, save_note
from cards_db import get_card, TYPE_COLORS, CHAR_COLORS
from theme import (
    STYLE, DELTA_TIP, COPIES_TIP,
    DARK_BG, PANEL_BG, CARD_BG, ACCENT, ACCENT2, WIN_COLOR, LOSS_COLOR, TEXT, MUTED,
)
from stats import compute_card_stats, filter_runs
from workers import RunLoader, ImageLoader, CardOcrWorker
from active_run import parse_active_run, find_active_run_path, ActiveRunState
from ui_utils import (
    make_label, SortableItem, ModeFilterWidget,
    make_char_combo, make_mode_filter, populate_char_combo,
    wr_item, delta_item, pct_item, num_item, bar_widget,
    repopulate_table, add_export_btn,
)


class RunHistoryTab(QWidget):
    run_selected = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # Filter bar
        filter_row = QHBoxLayout()
        self.char_filter = make_char_combo(self._apply_filter)
        self.outcome_filter = QComboBox()
        self.outcome_filter.addItems(["All Outcomes", "Wins", "Losses"])
        self.outcome_filter.currentTextChanged.connect(self._apply_filter)
        self.mode_filter = make_mode_filter(self._apply_filter)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search by character, act, killed by...")
        self.search_box.textChanged.connect(self._apply_filter)
        filter_row.addWidget(make_label("Filter:", bold=True))
        filter_row.addWidget(self.char_filter)
        filter_row.addWidget(self.outcome_filter)
        filter_row.addWidget(self.mode_filter)
        filter_row.addWidget(self.search_box)
        filter_row.addStretch()
        add_export_btn(filter_row, lambda: self.table, self)
        layout.addLayout(filter_row)

        self.stats_label = make_label("", color=MUTED)
        layout.addWidget(self.stats_label)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Character", "Mode", "Outcome", "Ascension", "Acts", "Floor", "Time", "Killed By"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(self.table.styleSheet() + "QTableWidget { alternate-background-color: #1e2a4a; }")
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table)

        self._all_runs: list[RunSummary] = []
        self._filtered: list[RunSummary] = []

    def load_runs(self, runs: list[RunSummary]):
        self._all_runs = runs
        populate_char_combo(self.char_filter, runs)
        self._apply_filter()

    def _apply_filter(self):
        char_f = self.char_filter.currentText()
        out_f = self.outcome_filter.currentText()
        mf = self.mode_filter
        search = self.search_box.text().lower()

        filtered = filter_runs(self._all_runs, char_f,
                               mf.include_sp, mf.include_mp, mf.include_daily)
        if out_f == "Wins":
            filtered = [r for r in filtered if r.win]
        elif out_f == "Losses":
            filtered = [r for r in filtered if not r.win]
        if search:
            filtered = [
                r for r in filtered
                if any(search in x.lower() for x in
                       (r.character_display, r.acts_display, r.killed_by, r.game_mode))
            ]

        wins = sum(1 for r in filtered if r.win)
        total = len(filtered)
        wr = f"{wins/total*100:.0f}%" if total else "—"
        self.stats_label.setText(f"{total} runs  |  {wins} wins  |  Win rate: {wr}")

        self._filtered = filtered
        self.table.setRowCount(len(filtered))
        for i, run in enumerate(filtered):
            self.table.setItem(i, 0, QTableWidgetItem(run.date.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(i, 1, QTableWidgetItem(run.character_display))
            if run.is_daily:
                mode_label, mode_color = "Daily", "#f39c12"
            elif run.is_multiplayer:
                mode_label, mode_color = f"MP ({run.player_count})", ACCENT2
            else:
                mode_label, mode_color = "SP", MUTED
            mode_item = QTableWidgetItem(mode_label)
            mode_item.setForeground(QColor(mode_color))
            self.table.setItem(i, 2, mode_item)
            outcome = "Win" if run.win else ("Abandoned" if run.was_abandoned else "Loss")
            outcome_item = QTableWidgetItem(outcome)
            outcome_item.setForeground(QColor(WIN_COLOR if run.win else LOSS_COLOR))
            self.table.setItem(i, 3, outcome_item)
            self.table.setItem(i, 4, QTableWidgetItem(str(run.ascension)))
            self.table.setItem(i, 5, QTableWidgetItem(run.acts_display))
            self.table.setItem(i, 6, QTableWidgetItem(str(run.floors_reached)))
            self.table.setItem(i, 7, QTableWidgetItem(run.run_time_display))
            self.table.setItem(i, 8, QTableWidgetItem(run.killed_by_display))

    def _on_select(self):
        if not self.table.selectedItems():
            return
        row = self.table.currentRow()
        if 0 <= row < len(self._filtered):
            self.run_selected.emit(self._filtered[row])


class RunDetailPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.title_label = make_label("Select a run to view details", bold=True, size=14)
        layout.addWidget(self.title_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.deck_table = self._make_list_table("Card", splitter, "Final Deck")
        self.relic_table = self._make_list_table("Relic", splitter, "Relics")
        layout.addWidget(splitter)

        layout.addWidget(make_label("Notes", bold=True))
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Add notes about this run...")
        self.notes_edit.setMaximumHeight(100)
        layout.addWidget(self.notes_edit)

        save_btn = QPushButton("Save Note")
        save_btn.clicked.connect(self._save_note)
        layout.addWidget(save_btn)

        self._current_run: RunSummary | None = None
        self._notes = load_notes()

    @staticmethod
    def _make_list_table(header: str, splitter: QSplitter, title: str) -> QTableWidget:
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(make_label(title, bold=True))
        table = QTableWidget()
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels([header])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        col.addWidget(table)
        splitter.addWidget(wrap)
        return table

    def show_run(self, run: RunSummary):
        self._current_run = run
        self._notes = load_notes()

        outcome = "WIN" if run.win else ("ABANDONED" if run.was_abandoned else "LOSS")
        color = WIN_COLOR if run.win else LOSS_COLOR
        self.title_label.setText(
            f"{run.character_display}  |  {outcome}  |  A{run.ascension}  |  {run.date.strftime('%Y-%m-%d')}"
        )
        self.title_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14pt;")

        self.deck_table.setRowCount(len(run.final_deck))
        for i, card_id in enumerate(sorted(run.final_deck)):
            self.deck_table.setItem(i, 0, QTableWidgetItem(fmt_card(card_id)))

        self.relic_table.setRowCount(len(run.final_relics))
        for i, relic_id in enumerate(run.final_relics):
            self.relic_table.setItem(i, 0, QTableWidgetItem(fmt_relic(relic_id)))

        self.notes_edit.setText(self._notes.get(run.filename, ""))

    def _save_note(self):
        if self._current_run:
            save_note(self._current_run.filename, self.notes_edit.toPlainText())


class CardStatsTab(QWidget):
    card_selected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        filter_row = QHBoxLayout()
        self.char_filter = make_char_combo(self._refresh)
        self.mode_filter = make_mode_filter(self._refresh)
        filter_row.addWidget(make_label("Character:", bold=True))
        filter_row.addWidget(self.char_filter)
        filter_row.addWidget(self.mode_filter)
        filter_row.addStretch()
        add_export_btn(filter_row, lambda: self.table, self)
        layout.addLayout(filter_row)

        layout.addWidget(make_label(
            "Win Δ = win rate WITH card minus win rate WITHOUT card (when offered but skipped). Green = picking helped.",
            color=MUTED, size=10,
        ))

        cols = ["Card", "Picked", "Skipped", "Pick%", "Avg Copies",
                "WR With", "WR Without", "Win Δ", "Avg Floor With", "Avg Floor Without"]
        self.table = QTableWidget()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table)
        QTimer.singleShot(0, self._set_header_tips)

        self._runs: list[RunSummary] = []

    def _set_header_tips(self):
        if self.table.horizontalHeaderItem(4):
            self.table.horizontalHeaderItem(4).setToolTip(COPIES_TIP)
        if self.table.horizontalHeaderItem(7):
            self.table.horizontalHeaderItem(7).setToolTip(DELTA_TIP)

    def _on_select(self):
        item = self.table.item(self.table.currentRow(), 0)
        if item and item.data(Qt.ItemDataRole.UserRole):
            self.card_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    def load_runs(self, runs: list[RunSummary]):
        self._runs = runs
        populate_char_combo(self.char_filter, runs)
        self._refresh()

    def _refresh(self):
        mf = self.mode_filter
        runs = filter_runs(self._runs, self.char_filter.currentText(),
                           mf.include_sp, mf.include_mp, mf.include_daily)
        stats = compute_card_stats(runs)
        rows = sorted(stats.items(), key=lambda x: x[1]["times_picked"], reverse=True)

        def populate():
            self.table.setRowCount(len(rows))
            for i, (card_id, s) in enumerate(rows):
                name_item = QTableWidgetItem(fmt_card(card_id))
                name_item.setData(Qt.ItemDataRole.UserRole, card_id)
                self.table.setItem(i, 0, name_item)
                self.table.setItem(i, 1, num_item(s["times_picked"]))
                self.table.setItem(i, 2, num_item(s["times_skipped"]))
                self.table.setItem(i, 3, pct_item(s["pick_rate"]))
                self.table.setItem(i, 4, self._avg_copies_item(s["avg_copies_per_run"]))
                self.table.setItem(i, 5, wr_item(s["with_wr"], s["with_runs"]))
                self.table.setItem(i, 6, wr_item(s["without_wr"], s["without_runs"]))
                self.table.setItem(i, 7, delta_item(s["win_delta"]))
                self.table.setItem(i, 8, num_item(s["with_avg_floor"]) if s["with_avg_floor"] else wr_item(None, 0))
                self.table.setItem(i, 9, num_item(s["without_avg_floor"]) if s["without_avg_floor"] else wr_item(None, 0))

        repopulate_table(self.table, populate)

    @staticmethod
    def _avg_copies_item(avg: float | None) -> SortableItem:
        item = SortableItem(f"{avg:.2f}×" if avg else "—")
        item.setData(Qt.ItemDataRole.UserRole, avg or -1.0)
        item.setForeground(QColor(WIN_COLOR if avg and avg >= 1.5 else (ACCENT2 if avg and avg > 1.0 else MUTED)))
        return item


class RelicStatsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        filter_row = QHBoxLayout()
        self.char_filter = make_char_combo(self._refresh)
        self.mode_filter = make_mode_filter(self._refresh)
        filter_row.addWidget(make_label("Character:", bold=True))
        filter_row.addWidget(self.char_filter)
        filter_row.addWidget(self.mode_filter)
        filter_row.addStretch()
        add_export_btn(filter_row, lambda: self.table, self)
        layout.addLayout(filter_row)

        layout.addWidget(make_label("Relics collected and win rate with each relic", color=MUTED))

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Relic", "Times Had", "Wins With", "Win Rate"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self._runs: list[RunSummary] = []

    def load_runs(self, runs: list[RunSummary]):
        self._runs = runs
        populate_char_combo(self.char_filter, runs)
        self._refresh()

    def _refresh(self):
        mf = self.mode_filter
        runs = filter_runs(self._runs, self.char_filter.currentText(),
                           mf.include_sp, mf.include_mp, mf.include_daily)

        had: dict[str, int] = defaultdict(int)
        won_with: dict[str, int] = defaultdict(int)
        for run in runs:
            for relic_id in run.final_relics:
                if not relic_id:
                    continue
                had[relic_id] += 1
                if run.win:
                    won_with[relic_id] += 1

        rows = [
            (fmt_relic(relic_id), count, won_with.get(relic_id, 0),
             won_with.get(relic_id, 0) / count if count else 0)
            for relic_id, count in had.items()
        ]
        rows.sort(key=lambda x: x[1], reverse=True)

        def populate():
            self.table.setRowCount(len(rows))
            for i, (name, count, wins, rate) in enumerate(rows):
                self.table.setItem(i, 0, QTableWidgetItem(name))
                self.table.setItem(i, 1, num_item(count))
                self.table.setItem(i, 2, num_item(wins))
                self.table.setItem(i, 3, pct_item(rate))

        repopulate_table(self.table, populate)


class StatCard(QFrame):
    """A small stat display card (big value + caption)."""
    def __init__(self, title: str, value: str = "—", color: str = TEXT):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background: {CARD_BG}; border-radius: 6px; }}")
        self.setMinimumWidth(140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self._val_label = make_label(value, bold=True, size=20, color=color)
        self._title_label = make_label(title, size=10, color=MUTED)
        layout.addWidget(self._val_label)
        layout.addWidget(self._title_label)

    def update(self, value: str, color: str = TEXT):
        self._val_label.setText(value)
        self._val_label.setStyleSheet(f"color: {color};")


class OverviewTab(QWidget):
    def __init__(self):
        super().__init__()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(18)

        filter_row = QHBoxLayout()
        self.char_filter = make_char_combo(self._refresh)
        self.mode_filter = make_mode_filter(self._refresh)
        filter_row.addWidget(make_label("Character:", bold=True))
        filter_row.addWidget(self.char_filter)
        filter_row.addWidget(self.mode_filter)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        stat_row = QHBoxLayout()
        stat_row.setSpacing(10)
        self._sc_runs = StatCard("Total Runs")
        self._sc_wins = StatCard("Wins", color=WIN_COLOR)
        self._sc_wr = StatCard("Win Rate")
        self._sc_time = StatCard("Avg Run Time")
        self._sc_floors = StatCard("Avg Floors")
        for sc in (self._sc_runs, self._sc_wins, self._sc_wr, self._sc_time, self._sc_floors):
            stat_row.addWidget(sc)
        stat_row.addStretch()
        layout.addLayout(stat_row)

        layout.addWidget(make_label("Most Killed By", bold=True, size=13))
        self.killer_table = self._make_table(["Killer", "Deaths", "% of Deaths"])
        layout.addWidget(self.killer_table)

        layout.addWidget(make_label("Results by Character", bold=True, size=13))
        self.char_table = self._make_table(["Character", "Runs", "Wins", "Win Rate", "Avg Floors"])
        layout.addWidget(self.char_table)

        layout.addStretch()
        self._runs: list[RunSummary] = []

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setMaximumHeight(220)
        return table

    def load_runs(self, runs: list[RunSummary]):
        self._runs = runs
        populate_char_combo(self.char_filter, runs)
        self._refresh()

    def _refresh(self):
        mf = self.mode_filter
        runs = filter_runs(self._runs, self.char_filter.currentText(),
                           mf.include_sp, mf.include_mp, mf.include_daily)

        total = len(runs)
        wins = sum(1 for r in runs if r.win)
        wr = wins / total if total else 0
        avg_time = sum(r.run_time_seconds for r in runs) / total if total else 0
        avg_floors = sum(r.floors_reached for r in runs) / total if total else 0

        m, s = divmod(int(avg_time), 60)
        h, m = divmod(m, 60)
        time_str = f"{h}h {m}m" if h else f"{m}m {s}s"

        self._sc_runs.update(str(total))
        self._sc_wins.update(str(wins), WIN_COLOR)
        self._sc_wr.update(f"{wr*100:.1f}%", WIN_COLOR if wr >= 0.5 else LOSS_COLOR)
        self._sc_time.update(time_str)
        self._sc_floors.update(f"{avg_floors:.1f}")

        # Most killed by (losses only)
        deaths: dict[str, int] = defaultdict(int)
        for r in runs:
            if r.killed_by and not r.win and not r.was_abandoned:
                deaths[r.killed_by_display] += 1
        total_deaths = sum(deaths.values())
        killer_rows = sorted(deaths.items(), key=lambda x: x[1], reverse=True)[:15]
        self.killer_table.setRowCount(len(killer_rows))
        for i, (name, count) in enumerate(killer_rows):
            self.killer_table.setItem(i, 0, QTableWidgetItem(name))
            self.killer_table.setItem(i, 1, num_item(count))
            self.killer_table.setItem(i, 2, pct_item(count / total_deaths if total_deaths else 0))

        # Character breakdown (always across all runs, ignoring the filter)
        char_runs: dict[str, list[RunSummary]] = defaultdict(list)
        for r in self._runs:
            char_runs[r.character_display].append(r)
        char_rows = []
        for char, rs in char_runs.items():
            cw = sum(1 for r in rs if r.win)
            ct = len(rs)
            char_rows.append((char, ct, cw, cw / ct if ct else 0,
                              sum(r.floors_reached for r in rs) / ct if ct else 0))
        char_rows.sort(key=lambda x: x[1], reverse=True)
        self.char_table.setRowCount(len(char_rows))
        for i, (char, ct, cw, cwr, cf) in enumerate(char_rows):
            self.char_table.setItem(i, 0, QTableWidgetItem(char))
            self.char_table.setItem(i, 1, num_item(ct))
            self.char_table.setItem(i, 2, num_item(cw))
            self.char_table.setItem(i, 3, pct_item(cwr))
            self.char_table.setItem(i, 4, num_item(cf))


class CardRankingsTab(QWidget):
    card_selected = pyqtSignal(str)

    _RANK_KEYS = {
        "Win Delta": lambda s: s["win_delta"] if s["win_delta"] is not None else -99,
        "Win Rate": lambda s: s["with_wr"] if s["with_wr"] is not None else -1,
        "Pick Rate": lambda s: s["pick_rate"],
        "Times Picked": lambda s: s["times_picked"],
        "Times in Winning Deck": lambda s: s["with_wins"],
    }
    _MIN_SAMPLE = {"Min 3 runs": 3, "Min 5 runs": 5, "Min 10 runs": 10, "Min 20 runs": 20, "No minimum": 1}

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        filter_row = QHBoxLayout()
        self.char_filter = make_char_combo(self._refresh)
        self.rank_by = QComboBox()
        self.rank_by.addItems(list(self._RANK_KEYS))
        self.rank_by.currentTextChanged.connect(self._refresh)
        self.min_sample = QComboBox()
        self.min_sample.addItems(list(self._MIN_SAMPLE))
        self.min_sample.setCurrentText("Min 5 runs")
        self.min_sample.currentTextChanged.connect(self._refresh)
        self.mode_filter = make_mode_filter(self._refresh)

        filter_row.addWidget(make_label("Character:", bold=True))
        filter_row.addWidget(self.char_filter)
        filter_row.addWidget(self.mode_filter)
        filter_row.addWidget(make_label("Rank by:", bold=True))
        filter_row.addWidget(self.rank_by)
        filter_row.addWidget(self.min_sample)
        filter_row.addStretch()
        add_export_btn(filter_row, lambda: self.table, self)
        layout.addLayout(filter_row)

        cols = ["#", "Card", "Win Delta", "WR With", "WR Without", "Pick%", "Picked", "Avg Floor With"]
        self.table = QTableWidget()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table)
        QTimer.singleShot(0, self._set_header_tip)

        self._runs: list[RunSummary] = []

    def _set_header_tip(self):
        if self.table.horizontalHeaderItem(2):
            self.table.horizontalHeaderItem(2).setToolTip(DELTA_TIP)

    def _on_select(self):
        item = self.table.item(self.table.currentRow(), 1)  # card_id stored on name column
        if item and item.data(Qt.ItemDataRole.UserRole):
            self.card_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    def load_runs(self, runs: list[RunSummary]):
        self._runs = runs
        populate_char_combo(self.char_filter, runs)
        self._refresh()

    def _refresh(self):
        mf = self.mode_filter
        runs = filter_runs(self._runs, self.char_filter.currentText(),
                           mf.include_sp, mf.include_mp, mf.include_daily)
        min_n = self._MIN_SAMPLE.get(self.min_sample.currentText(), 5)
        sort_key = self._RANK_KEYS.get(self.rank_by.currentText(), self._RANK_KEYS["Win Delta"])

        stats = compute_card_stats(runs)
        rows = [(cid, s) for cid, s in stats.items() if s["with_runs"] >= min_n]
        rows.sort(key=lambda item: sort_key(item[1]), reverse=True)

        def populate():
            self.table.setRowCount(len(rows))
            for i, (card_id, s) in enumerate(rows):
                rank_item = num_item(i + 1)
                rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                rank_item.setForeground(QColor(MUTED))
                self.table.setItem(i, 0, rank_item)
                name_item = QTableWidgetItem(fmt_card(card_id))
                name_item.setData(Qt.ItemDataRole.UserRole, card_id)
                self.table.setItem(i, 1, name_item)
                self.table.setItem(i, 2, delta_item(s["win_delta"]))
                self.table.setItem(i, 3, wr_item(s["with_wr"], s["with_runs"]))
                self.table.setItem(i, 4, wr_item(s["without_wr"], s["without_runs"]))
                self.table.setItem(i, 5, pct_item(s["pick_rate"]))
                self.table.setItem(i, 6, num_item(s["times_picked"]))
                self.table.setItem(i, 7, num_item(s["with_avg_floor"]) if s["with_avg_floor"] else wr_item(None, 0))

        repopulate_table(self.table, populate)


class CardPreviewPanel(QWidget):
    """Visual card panel: art, description, and per-card run statistics."""
    IMG_W, IMG_H = 120, 165
    MAX_FLOOR = 45.0  # rough StS2 max, for floor bar scaling

    def __init__(self):
        super().__init__()
        self._runs: list[RunSummary] = []
        self._char_filter = "All Characters"
        self._img_loader: ImageLoader | None = None
        self._img_label: QLabel | None = None
        header_h = self.IMG_H + 24

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header_placeholder = make_label("Click any card to see details", color=MUTED, size=12)
        self._header_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_placeholder.setFixedHeight(header_h)
        outer.addWidget(self._header_placeholder)

        self._header_frame = QFrame()
        self._header_frame.setFixedHeight(header_h)
        self._header_frame.setVisible(False)
        outer.addWidget(self._header_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, stretch=1)

        inner = QWidget()
        scroll.setWidget(inner)
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(14, 8, 14, 14)
        self._layout.setSpacing(12)
        self._layout.addStretch()

        self._content_widgets: list[QWidget] = []

    def set_runs(self, runs: list[RunSummary], char_filter: str = "All Characters"):
        self._runs = runs
        self._char_filter = char_filter

    def _set_card_image(self, path_str: str):
        if not self._img_label:
            return
        if path_str:
            pix = QPixmap(path_str)
            if not pix.isNull():
                self._img_label.setPixmap(pix.scaled(
                    self.IMG_W, self.IMG_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                self._img_label.setText("")
                return
        self._img_label.setText("No image")

    def _add(self, w: QWidget):
        self._content_widgets.append(w)
        self._layout.insertWidget(self._layout.count() - 1, w)  # before the trailing stretch

    def show_card(self, card_id: str):
        if self._img_loader and self._img_loader.isRunning():
            self._img_loader.done.disconnect()
            self._img_loader = None
        self._img_label = None

        for w in self._content_widgets:
            self._layout.removeWidget(w)
            w.deleteLater()
        self._content_widgets.clear()

        card_char = self._build_header(card_id)

        self._img_loader = ImageLoader(card_id, card_char if card_char != "Any" else None)
        self._img_loader.done.connect(self._set_card_image)
        self._img_loader.start()

        runs = filter_runs(self._runs, self._char_filter, "All Modes")
        s = compute_card_stats(runs).get(card_id)
        if not s:
            self._add(make_label("No run data for this card yet.", color=MUTED))
            return
        self._build_stats(card_id, s)

    def _build_header(self, card_id: str) -> str:
        """Rebuild the fixed-height header frame in place; returns the card's character."""
        db = get_card(card_id)
        card_type = db["type"] if db else "Unknown"
        card_char = db["char"] if db else "Any"
        card_cost = db["cost"] if db else "?"
        card_desc = db["desc"] if db else None
        type_color = TYPE_COLORS.get(card_type, MUTED)
        char_color = CHAR_COLORS.get(card_char, MUTED)

        self._header_frame.setStyleSheet(
            f"QFrame {{ background: {CARD_BG}; border-radius: 8px; border-left: 4px solid {type_color}; }}"
        )
        nf_layout = self._header_frame.layout()
        if nf_layout:
            while nf_layout.count():
                item = nf_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        else:
            nf_layout = QHBoxLayout(self._header_frame)
            nf_layout.setContentsMargins(12, 12, 12, 12)
            nf_layout.setSpacing(12)

        img_lbl = QLabel("...")
        img_lbl.setFixedSize(self.IMG_W, self.IMG_H)
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setStyleSheet(f"color: {MUTED}; background: {DARK_BG}; border-radius: 6px; font-size: 9pt;")
        nf_layout.addWidget(img_lbl)
        self._img_label = img_lbl

        right = QWidget()
        right.setStyleSheet("background: transparent;")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.addWidget(make_label(fmt_card(card_id), bold=True, size=15))
        cost_lbl = make_label(f" {card_cost} ", bold=True, size=13)
        cost_lbl.setStyleSheet(f"color: white; background: {ACCENT}; border-radius: 10px; padding: 0 4px;")
        top_row.addStretch()
        top_row.addWidget(cost_lbl)
        rl.addLayout(top_row)

        badge_row = QHBoxLayout()
        badge_row.addWidget(self._badge(card_type, type_color))
        badge_row.addWidget(self._badge(card_char, char_color))
        badge_row.addStretch()
        rl.addLayout(badge_row)

        if card_desc:
            desc_lbl = QLabel(card_desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11pt; padding-top: 4px; background: transparent;")
            rl.addWidget(desc_lbl)
        else:
            rl.addWidget(make_label("No description — check in-game encyclopedia.", size=10, color=MUTED))

        nf_layout.addWidget(right, stretch=1)
        self._header_placeholder.setVisible(False)
        self._header_frame.setVisible(True)
        return card_char

    @staticmethod
    def _badge(text: str, color: str) -> QLabel:
        lbl = make_label(f"  {text}  ", size=10)
        lbl.setStyleSheet(f"color: white; background: {color}; border-radius: 4px; padding: 1px 4px;")
        return lbl

    def _build_stats(self, card_id: str, s: dict):
        # Summary mini-stats
        delta = s["win_delta"]
        delta_color = WIN_COLOR if (delta or 0) > 0.05 else (LOSS_COLOR if (delta or 0) < -0.05 else MUTED)
        delta_str = (("+" if delta > 0 else "") + f"{delta*100:.1f}pp") if delta is not None else "—"
        avg = s["avg_copies_per_run"]
        avg_color = WIN_COLOR if (avg or 0) >= 1.5 else (ACCENT2 if (avg or 0) > 1.0 else MUTED)

        summary = QWidget()
        sr = QHBoxLayout(summary)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        sr.addWidget(self._mini_stat("Runs Picked", str(s["times_picked"])))
        sr.addWidget(self._mini_stat("Pick Rate", f"{s['pick_rate']*100:.0f}%",
                                     WIN_COLOR if s["pick_rate"] >= 0.5 else LOSS_COLOR))
        sr.addWidget(self._mini_stat("Avg Copies", f"{avg:.2f}×" if avg else "—", avg_color))
        sr.addWidget(self._mini_stat("Win Δ", delta_str, delta_color))
        sr.addStretch()
        self._add(summary)

        # Win-rate comparison bars
        self._add(make_label("Win Rate Comparison", bold=True, size=11))
        wr_frame, wrf = self._section_frame()
        if s["with_wr"] is not None:
            wrf.addWidget(bar_widget(s["with_wr"], WIN_COLOR,
                                     f"With card  ({s['with_runs']} runs)", f"{s['with_wr']*100:.1f}%"))
        if s["without_wr"] is not None:
            wrf.addWidget(bar_widget(s["without_wr"], "#888",
                                     f"Without card  ({s['without_runs']} runs)", f"{s['without_wr']*100:.1f}%"))
        wrf.addWidget(bar_widget(s["pick_rate"], ACCENT2,
                                 "Pick rate when offered", f"{s['pick_rate']*100:.1f}%"))
        self._add(wr_frame)

        # Floor depth bars
        self._add(make_label("Average Floors Reached", bold=True, size=11))
        floor_frame, ff = self._section_frame()
        for avg_floor, color, n in (
            (s["with_avg_floor"], WIN_COLOR, s["with_runs"]),
            (s["without_avg_floor"], "#888", s["without_runs"]),
        ):
            if avg_floor:
                label = "With card" if color == WIN_COLOR else "Without card"
                ff.addWidget(bar_widget(min(avg_floor / self.MAX_FLOOR, 1.0), color,
                                        f"{label}  ({n} runs)", f"{avg_floor:.1f} floors"))
        self._add(floor_frame)

        # Run breakdown
        self._add(make_label("Run Breakdown", bold=True, size=11))
        rb_frame = QFrame()
        rb_frame.setStyleSheet(f"QFrame {{ background: {PANEL_BG}; border-radius: 6px; }}")
        rb = QGridLayout(rb_frame)
        rb.setContentsMargins(12, 10, 12, 10)
        rb.setHorizontalSpacing(16)
        rb.setVerticalSpacing(4)
        breakdown = [
            ("Runs with card", str(s["with_runs"]), TEXT),
            ("Wins with card", str(s["with_wins"]), WIN_COLOR),
            ("Runs offered, not taken", str(s["without_runs"]), TEXT),
            ("Wins without card", str(s["without_wins"]), TEXT),
        ]
        for row, (label, val, color) in enumerate(breakdown):
            rb.addWidget(make_label(label, size=11, color=MUTED), row, 0)
            rb.addWidget(make_label(val, size=11, bold=True, color=color), row, 1)
        self._add(rb_frame)

        # Recent runs with the card
        recent = [r for r in self._runs
                  if (self._char_filter == "All Characters" or r.character_display == self._char_filter)
                  and card_id in r.final_deck][:8]
        if recent:
            self._add(make_label("Recent Runs With Card", bold=True, size=11))
            runs_frame, rfl = self._section_frame(spacing=4, pad=(12, 8, 12, 8))
            for r in recent:
                row_w = QWidget()
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, 0, 0, 0)
                outcome_lbl = make_label(f"[{'W' if r.win else 'L'}]", bold=True, size=10,
                                         color=WIN_COLOR if r.win else LOSS_COLOR)
                outcome_lbl.setFixedWidth(28)
                row_l.addWidget(outcome_lbl)
                row_l.addWidget(make_label(r.date.strftime("%m/%d"), size=10, color=MUTED))
                row_l.addWidget(make_label(r.character_display, size=10))
                row_l.addStretch()
                row_l.addWidget(make_label(f"A{r.ascension}", size=10, color=MUTED))
                rfl.addWidget(row_w)
            self._add(runs_frame)

    @staticmethod
    def _mini_stat(title: str, val: str, color: str = TEXT) -> QFrame:
        f = QFrame()
        f.setStyleSheet(f"QFrame {{ background: {PANEL_BG}; border-radius: 6px; }}")
        fl = QVBoxLayout(f)
        fl.setContentsMargins(10, 8, 10, 8)
        fl.setSpacing(1)
        fl.addWidget(make_label(val, bold=True, size=14, color=color))
        fl.addWidget(make_label(title, size=9, color=MUTED))
        return f

    @staticmethod
    def _section_frame(spacing: int = 8, pad: tuple = (12, 10, 12, 10)) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background: {PANEL_BG}; border-radius: 6px; }}")
        box = QVBoxLayout(frame)
        box.setContentsMargins(*pad)
        box.setSpacing(spacing)
        return frame, box


class ActiveRunTab(QWidget):
    """Live view of the current in-progress run, updated whenever the save file changes."""

    POLL_MS = 1_000
    ocr_updated = pyqtSignal(list)   # emits ocr_results whenever they change

    def __init__(self):
        super().__init__()
        self._run: ActiveRunState | None = None
        self._card_stats: dict = {}   # populated from historical runs
        self._relic_stats: dict = {}  # relic_id -> {with_wr, with_runs}
        self._save_path: Path | None = None
        self._ocr_worker = None
        self._ocr_scanning = False           # True while a worker is in-flight
        self._ocr_results: list = []        # [(card_id_or_None, raw_name), ...]
        self._ocr_cache: list = [None, None, None]  # locked card_id per slot
        self._ocr_votes: list = [[], [], []]         # rolling window of raw scan results per slot
        self._ocr_empty_streak = 0           # consecutive all-empty OCR scans
        self._ocr_overlay_visible: bool = False
        self._ocr_enabled: bool = True
        self._last_save_mtime: float = 0.0
        self._reward_encounter_id: str | None = None
        # Persistent refs into the live card reward panel for in-place updates
        self._ocr_status_lbl: QLabel | None = None
        self._ocr_slot_frames: list = []   # [(frame, name_lbl, wr_lbl, wo_lbl, avg_lbl, d_lbl)]
        self.ocr_updated.connect(self._apply_ocr_to_panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._inner = QWidget()
        scroll.setWidget(self._inner)
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(14)

        # Placeholder shown when no active run
        self._placeholder = make_label(
            "No active run detected — start a run in StS2 and it will appear here.",
            color=MUTED, size=13,
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder)
        self._layout.addStretch()

        self._content_widgets: list[QWidget] = []

        # File watcher for save file
        self._watcher = QFileSystemWatcher()
        self._watcher.fileChanged.connect(self._on_file_changed)

        # Godot log watcher — dismisses overlay immediately on card selection
        self._log_watcher = QFileSystemWatcher()
        self._log_watcher.fileChanged.connect(self._on_log_changed)
        self._log_pos: int = 0

        # Fallback poll timer
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self.refresh)
        self._poll_timer.start(self.POLL_MS)

    def set_save_path(self, history_path: Path | None):
        """Called by MainWindow when the save folder is known."""
        if history_path is None:
            return
        save_file = history_path.parent / "current_run.save"
        self._save_path = save_file
        if save_file.exists():
            if str(save_file) not in self._watcher.files():
                self._watcher.addPath(str(save_file))
        log_file = history_path.parent / "logs" / "godot.log"
        if log_file.exists():
            self._log_pos = log_file.stat().st_size  # start at end, skip old entries
            if str(log_file) not in self._log_watcher.files():
                self._log_watcher.addPath(str(log_file))
        self.refresh()

    def update_historical_stats(self, runs):
        """Called by MainWindow after runs load so we can show historical card/relic data."""
        self._card_stats = compute_card_stats(runs)
        relic_won: dict[str, int] = defaultdict(int)
        relic_total: dict[str, int] = defaultdict(int)
        for r in runs:
            for rid in r.final_relics:
                if rid:
                    relic_total[rid] += 1
                    if r.win:
                        relic_won[rid] += 1
        self._relic_stats = {
            rid: {"with_wr": relic_won[rid] / total, "with_runs": total}
            for rid, total in relic_total.items() if total
        }
        if self._run:
            self._render()  # refresh display with new stats

    def _on_file_changed(self, path: str):
        # Re-watch: some editors/games write by replace, which removes the watch
        if not self._watcher.files().__contains__(path):
            self._watcher.addPath(path)
        QTimer.singleShot(200, self.refresh)   # tiny delay for write to complete

    def _on_log_changed(self, path: str):
        if path not in self._log_watcher.files():
            self._log_watcher.addPath(path)
        try:
            log = Path(path)
            size = log.stat().st_size
            if size < self._log_pos:
                self._log_pos = 0  # file rotated/truncated
            with open(log, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._log_pos)
                new_text = f.read()
                self._log_pos = f.tell()
            if "from card reward" in new_text:
                # Card picked — dismiss overlay immediately
                self._ocr_scanning = False
                self.ocr_updated.emit([])
        except Exception:
            pass

    def refresh(self):
        if self._save_path is None:
            active_path = find_active_run_path()
            if active_path:
                self._save_path = active_path
                self._watcher.addPath(str(active_path))
        if self._save_path is None or not self._save_path.exists():
            self._show_placeholder()
            return
        import os
        try:
            mtime = os.path.getmtime(self._save_path)
        except OSError:
            mtime = 0.0
        run = parse_active_run(self._save_path)
        if run is None:
            self._show_placeholder()
            return
        # Only re-render if the file actually changed on disk
        if self._run and mtime == self._last_save_mtime:
            return
        self._last_save_mtime = mtime
        self._run = run
        if run.is_reward_pending:
            if run.reward_encounter_id != self._reward_encounter_id:
                # New encounter — dismiss old overlay and reset OCR for new cards
                self._reward_encounter_id = run.reward_encounter_id
                self._ocr_cache = [None, None, None]
                self._ocr_votes = [[], [], []]
                self._ocr_results = []
                self._ocr_empty_streak = 0
                self._ocr_scanning = False
                self._ocr_overlay_visible = False
                self.ocr_updated.emit([])
                # Wait 1s for card selection screen to finish loading
                QTimer.singleShot(500, self._start_ocr)
            else:
                self._start_ocr()
        else:
            self._reward_encounter_id = None
            self._ocr_scanning = False
            self._ocr_results = []
            self._ocr_cache = [None, None, None]
            self._ocr_votes = [[], [], []]
            self._ocr_empty_streak = 0
            self._ocr_overlay_visible = False
            self.ocr_updated.emit([])
        self._render()

    def set_ocr_enabled(self, enabled: bool) -> None:
        self._ocr_enabled = enabled
        if not enabled:
            self._ocr_scanning = False
            self._ocr_overlay_visible = False
            self.ocr_updated.emit([])

    def _start_ocr(self):
        from card_ocr import is_available
        if not is_available() or self._ocr_scanning or self._reward_encounter_id is None or not self._ocr_enabled:
            return
        self._ocr_scanning = True
        all_ids = list(self._card_stats.keys()) if self._card_stats else []
        self._ocr_worker = CardOcrWorker(all_ids)
        self._ocr_worker.done.connect(self._on_ocr_done)
        self._ocr_worker.start()

    def _rescan(self):
        self._ocr_cache = [None, None, None]
        self._ocr_votes = [[], [], []]
        self._ocr_results = []
        self._ocr_empty_streak = 0
        self._ocr_scanning = False
        self.ocr_updated.emit([])
        QTimer.singleShot(0, self._after_rescan)

    def _after_rescan(self):
        self._render()
        self._start_ocr()

    def _on_ocr_done(self, results: list):
        self._ocr_scanning = False
        if self._reward_encounter_id is None:
            return  # reward cleared while scan was in flight

        _OCR_MIN_SAMPLE = 5   # scans before a slot can lock
        _OCR_LOCK_FRAC  = 0.80  # fraction of window that must agree

        all_found = all(c is not None for c in self._ocr_cache)

        if all_found:
            # Watch mode: toggle overlay as the card screen appears/disappears
            # (e.g. player opens deck view). Stop after 30 consecutive misses
            # (~15s) which means they've fully left the reward screen.
            known = {c for c in self._ocr_cache if c is not None}
            still_visible = any(cid in known for cid, _ in (results or []))
            if still_visible:
                self._ocr_empty_streak = 0
                if not self._ocr_overlay_visible:
                    self._ocr_overlay_visible = True
                    self.ocr_updated.emit(self._ocr_results)
            else:
                self._ocr_empty_streak += 1
                if self._ocr_empty_streak >= 2 and self._ocr_overlay_visible:
                    self._ocr_overlay_visible = False
                    self.ocr_updated.emit([])
                if self._ocr_empty_streak >= 30:
                    self._ocr_empty_streak = 0
                    return
            QTimer.singleShot(500, self._start_ocr)
            return

        # Only accumulate votes once all three zones are returning text —
        # confirms we're on the card selection screen, not an intermediate screen.
        all_zones_have_text = results and len(results) == 3 and all(raw != "" for _, raw in results)
        if all_zones_have_text:
            for i, (card_id, _) in enumerate(results):
                if card_id is not None and self._ocr_cache[i] is None:
                    self._ocr_votes[i].append(card_id)
                    if len(self._ocr_votes[i]) > 10:
                        self._ocr_votes[i].pop(0)
                    n = len(self._ocr_votes[i])
                    if n >= _OCR_MIN_SAMPLE:
                        from collections import Counter
                        top_id, top_n = Counter(self._ocr_votes[i]).most_common(1)[0]
                        if top_n / n >= _OCR_LOCK_FRAC:
                            self._ocr_cache[i] = top_id

        # Build display from locked slots + current leading candidate for unlocked
        from collections import Counter as _Ctr
        display = []
        for i in range(3):
            if self._ocr_cache[i]:
                display.append(self._ocr_cache[i])
            elif self._ocr_votes[i]:
                display.append(_Ctr(self._ocr_votes[i]).most_common(1)[0][0])
            else:
                display.append(None)

        raw_by_pos = {i: raw for i, (_, raw) in enumerate(results or [])}
        all_raw_empty = not results or all(raw == "" for _, raw in results)
        if any(display):
            self._ocr_empty_streak = 0
            self._ocr_results = [(display[i], raw_by_pos.get(i, "")) for i in range(3)]
            self.ocr_updated.emit(self._ocr_results)
        elif all_raw_empty:
            # Truly nothing on screen — count toward stop threshold
            self._ocr_empty_streak += 1
            if self._ocr_empty_streak >= 5:
                self._ocr_empty_streak = 0
                return
        # else: OCR found text but couldn't match cards yet — keep scanning

        if all(c is not None for c in self._ocr_cache):
            self._ocr_empty_streak = 0
            QTimer.singleShot(500, self._start_ocr)
            return

        self._start_ocr()

    def _show_placeholder(self):
        self._run = None
        self._clear_content()
        self._placeholder.setVisible(True)

    def _clear_content(self):
        self._ocr_status_lbl = None
        self._ocr_slot_frames = []
        for w in self._content_widgets:
            self._layout.removeWidget(w)
            w.deleteLater()
        self._content_widgets.clear()

    def _add(self, w: QWidget):
        self._content_widgets.append(w)
        self._layout.insertWidget(self._layout.count() - 1, w)

    def _build_card_reward_panel(self) -> QFrame:
        """Build the card reward panel with pre-created slots; labels updated in-place by _apply_ocr_to_panel."""
        panel = QFrame()
        panel.setStyleSheet(
            f"QFrame {{ background: {PANEL_BG}; border-radius: 8px; "
            f"border: 2px solid {ACCENT}; }}"
        )
        col = QVBoxLayout(panel)
        col.setContentsMargins(16, 12, 16, 14)
        col.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.addWidget(make_label("Card Reward", bold=True, size=14, color=ACCENT))
        self._ocr_status_lbl = make_label("Reading screen…", size=11, color=MUTED)
        title_row.addWidget(self._ocr_status_lbl)
        title_row.addStretch()
        rescan_btn = QPushButton("Re-scan")
        rescan_btn.setStyleSheet(
            f"background: {CARD_BG}; color: {MUTED}; border: 1px solid {MUTED};"
            "padding: 2px 10px; border-radius: 4px; font-size: 10pt;"
        )
        rescan_btn.clicked.connect(self._rescan)
        title_row.addWidget(rescan_btn)
        col.addLayout(title_row)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self._ocr_slot_frames = []
        for _ in range(3):
            card_frame = QFrame()
            card_frame.setStyleSheet(f"QFrame {{ background: {CARD_BG}; border-radius: 6px; border-left: 4px solid {MUTED}; }}")
            card_frame.setVisible(False)
            cl = QVBoxLayout(card_frame)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(4)
            name_lbl = make_label("", bold=True, size=12)
            wr_lbl   = make_label("", size=11, color=MUTED)
            wo_lbl   = make_label("", size=11, color=MUTED)
            avg_lbl  = make_label("", size=11, color=MUTED)
            d_lbl    = make_label("", size=11, color=MUTED)
            for lbl in (name_lbl, wr_lbl, wo_lbl, avg_lbl, d_lbl):
                cl.addWidget(lbl)
            self._ocr_slot_frames.append((card_frame, name_lbl, wr_lbl, wo_lbl, avg_lbl, d_lbl))
            cards_row.addWidget(card_frame, stretch=1)
        col.addLayout(cards_row)

        # Populate with any results already available
        self._apply_ocr_to_panel(self._ocr_results)
        return panel

    def _apply_ocr_to_panel(self, ocr_results: list):
        """Update the card reward panel labels in-place — never creates or destroys widgets."""
        if not self._ocr_slot_frames:
            return

        has_any = any(cid for cid, _ in ocr_results) if ocr_results else False
        if self._ocr_status_lbl:
            self._ocr_status_lbl.setVisible(not has_any)

        best_delta = None
        if has_any:
            deltas = [self._card_stats[cid]["win_delta"] for cid, _ in ocr_results
                      if cid and cid in self._card_stats and self._card_stats[cid]["win_delta"] is not None]
            best_delta = max(deltas) if deltas else None

        from cards_db import get_card, TYPE_COLORS
        for i, (card_frame, name_lbl, wr_lbl, wo_lbl, avg_lbl, d_lbl) in enumerate(self._ocr_slot_frames):
            card_id = ocr_results[i][0] if ocr_results and i < len(ocr_results) else None
            if not card_id:
                card_frame.setVisible(False)
                continue

            db = get_card(card_id)
            type_color = TYPE_COLORS.get(db["type"] if db else "Unknown", MUTED)
            card_frame.setStyleSheet(
                f"QFrame {{ background: {CARD_BG}; border-radius: 6px; border-left: 4px solid {type_color}; }}"
            )
            name_lbl.setText(fmt_card(card_id))

            s = self._card_stats.get(card_id)
            if s and s["with_wr"] is not None:
                wr = s["with_wr"]
                wr_color = WIN_COLOR if wr >= 0.5 else LOSS_COLOR
                wr_lbl.setText(f"WR with:  {wr*100:.0f}%  ({s['with_runs']})")
                wr_lbl.setStyleSheet(f"color: {wr_color};")

                wor = s["without_wr"]
                wo_lbl.setText(f"WR w/out: {wor*100:.0f}%  ({s['without_runs']})" if wor is not None else "WR w/out: —")
                wo_lbl.setStyleSheet(f"color: {WIN_COLOR if (wor or 0) >= 0.5 else (LOSS_COLOR if wor is not None else MUTED)};")

                avg = s["avg_copies_per_run"]
                avg_color = WIN_COLOR if (avg or 0) >= 1.5 else (ACCENT2 if (avg or 0) > 1.0 else MUTED)
                avg_lbl.setText(f"Avg:      {f'{avg:.2f}×' if avg else '—'} in deck")
                avg_lbl.setStyleSheet(f"color: {avg_color};")

                delta = s["win_delta"]
                if delta is not None:
                    sign = "+" if delta > 0 else ""
                    is_best = best_delta is not None and abs(delta - best_delta) < 0.001
                    d_color = WIN_COLOR if delta > 0.05 else (LOSS_COLOR if delta < -0.05 else MUTED)
                    d_lbl.setText(f"Δ:        {sign}{delta*100:.1f}pp" + (" ★" if is_best else ""))
                    d_lbl.setStyleSheet(f"color: {d_color}; {'font-weight: bold;' if is_best else ''}")
                else:
                    d_lbl.setText("Δ:        —")
                    d_lbl.setStyleSheet(f"color: {MUTED};")
            else:
                wr_lbl.setText("No history yet")
                wr_lbl.setStyleSheet(f"color: {MUTED};")
                wo_lbl.setText(""); avg_lbl.setText(""); d_lbl.setText("")

            card_frame.setVisible(True)

    def _render(self):
        self._clear_content()
        self._placeholder.setVisible(False)
        r = self._run

        # ── Card Reward panel (shown when fight just won, reward pending) ──
        if r.is_reward_pending:
            self._add(self._build_card_reward_panel())

        # ── Header strip ──────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"QFrame {{ background: {CARD_BG}; border-radius: 8px; }}")
        hrow = QHBoxLayout(header)
        hrow.setContentsMargins(16, 12, 16, 12)
        hrow.setSpacing(24)

        char_color = CHAR_COLORS.get(r.character_display, TEXT)
        hrow.addWidget(make_label(r.character_display, bold=True, size=18, color=char_color))

        mode_str = "Daily" if r.is_daily else (f"MP ({r.player_count}p)" if r.is_multiplayer else "SP")
        hrow.addWidget(make_label(f"A{r.ascension}  •  {mode_str}", size=12, color=MUTED))
        hrow.addWidget(make_label(f"{r.act_display}  •  Floor {r.floors_completed}", size=13))
        hrow.addStretch()

        # HP bar
        hp_color = WIN_COLOR if r.hp_pct > 0.5 else ("#f39c12" if r.hp_pct > 0.25 else LOSS_COLOR)
        hp_frame = QFrame()
        hp_frame.setStyleSheet(f"QFrame {{ background: {PANEL_BG}; border-radius: 6px; }}")
        hp_col = QVBoxLayout(hp_frame)
        hp_col.setContentsMargins(10, 6, 10, 6)
        hp_col.setSpacing(2)
        hp_col.addWidget(make_label(f"HP  {r.current_hp} / {r.max_hp}", bold=True, size=12, color=hp_color))
        hp_col.addWidget(bar_widget(r.hp_pct, hp_color))
        hrow.addWidget(hp_frame)

        # Gold
        hrow.addWidget(make_label(f"💰 {r.gold}", bold=True, size=13, color="#f1c40f"))

        # Potions
        if r.potions:
            pot_str = "  ".join(p.display_name for p in r.potions)
            hrow.addWidget(make_label(f"🧪 {pot_str}", size=11, color=MUTED))

        self._add(header)

        # ── Deck ──────────────────────────────────────────────────────
        self._add(make_label("Deck", bold=True, size=13))

        deck_frame = QFrame()
        deck_frame.setStyleSheet(f"QFrame {{ background: {PANEL_BG}; border-radius: 6px; }}")
        deck_grid = QGridLayout(deck_frame)
        deck_grid.setContentsMargins(12, 10, 12, 10)
        deck_grid.setHorizontalSpacing(12)
        deck_grid.setVerticalSpacing(6)
        deck_grid.setColumnStretch(0, 3)  # card name
        deck_grid.setColumnStretch(1, 2)  # description
        deck_grid.setColumnStretch(2, 1)  # WR with
        deck_grid.setColumnStretch(3, 1)  # win delta

        # Header row
        for col, txt in enumerate(["Card", "Effect", "WR With", "Win Δ"]):
            lbl = make_label(txt, bold=True, size=10, color=MUTED)
            deck_grid.addWidget(lbl, 0, col)

        # Sort deck by floor added
        sorted_deck = sorted(r.deck, key=lambda c: c.floor_added)
        for row, card in enumerate(sorted_deck, start=1):
            db = get_card(card.card_id)
            card_type = db["type"] if db else "Skill"
            type_color = TYPE_COLORS.get(card_type, MUTED)

            name_lbl = make_label(card.display_name, size=11)
            name_lbl.setStyleSheet(f"color: {TEXT}; border-left: 3px solid {type_color}; padding-left: 6px;")
            deck_grid.addWidget(name_lbl, row, 0)

            desc = (db["desc"] if db else "") or ""
            desc_lbl = QLabel(desc[:80] + ("…" if len(desc) > 80 else ""))
            desc_lbl.setStyleSheet(f"color: {MUTED}; font-size: 10pt;")
            desc_lbl.setWordWrap(False)
            deck_grid.addWidget(desc_lbl, row, 1)

            # Historical stats for this card
            s = self._card_stats.get(card.card_id)
            if s and s["with_wr"] is not None:
                wr = s["with_wr"]
                wr_color = WIN_COLOR if wr >= 0.5 else LOSS_COLOR
                wr_lbl = make_label(f"{wr*100:.0f}%  ({s['with_runs']})", size=10, color=wr_color)
            else:
                wr_lbl = make_label("—", size=10, color=MUTED)
            deck_grid.addWidget(wr_lbl, row, 2)

            if s and s["win_delta"] is not None:
                d_val = s["win_delta"]
                sign = "+" if d_val > 0 else ""
                d_color = WIN_COLOR if d_val > 0.05 else (LOSS_COLOR if d_val < -0.05 else MUTED)
                d_lbl = make_label(f"{sign}{d_val*100:.0f}pp", size=10, color=d_color)
            else:
                d_lbl = make_label("—", size=10, color=MUTED)
            deck_grid.addWidget(d_lbl, row, 3)

        self._add(deck_frame)

        # ── Relics ────────────────────────────────────────────────────
        self._add(make_label("Relics", bold=True, size=13))

        relic_frame = QFrame()
        relic_frame.setStyleSheet(f"QFrame {{ background: {PANEL_BG}; border-radius: 6px; }}")
        relic_grid = QGridLayout(relic_frame)
        relic_grid.setContentsMargins(12, 10, 12, 10)
        relic_grid.setHorizontalSpacing(24)
        relic_grid.setVerticalSpacing(4)
        relic_grid.setColumnStretch(0, 3)
        relic_grid.setColumnStretch(1, 1)

        for col, txt in enumerate(["Relic", "Win Rate"]):
            relic_grid.addWidget(make_label(txt, bold=True, size=10, color=MUTED), 0, col)

        for row, relic in enumerate(r.relics, start=1):
            relic_grid.addWidget(make_label(relic.display_name, size=11), row, 0)
            rs = self._relic_stats.get(relic.relic_id)
            if rs:
                wr = rs["with_wr"]
                wr_color = WIN_COLOR if wr >= 0.5 else LOSS_COLOR
                relic_grid.addWidget(make_label(f"{wr*100:.0f}%  ({rs['with_runs']})", size=10, color=wr_color), row, 1)
            else:
                relic_grid.addWidget(make_label("—", size=10, color=MUTED), row, 1)

        self._add(relic_frame)


class ZoneCalibrationOverlay(QWidget):
    """Interactive overlay showing the OCR search zones as draggable/resizable boxes."""

    zones_saved = pyqtSignal()
    _COLORS = ["#00ff88", "#00ccff", "#ff9900"]

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        from card_ocr import get_game_window_rect, _CARD_X, _SEARCH_Y
        game_rect = get_game_window_rect()
        if game_rect:
            self._gx, self._gy, self._gw, self._gh = game_rect
        else:
            geo = QApplication.primaryScreen().geometry()
            self._gx, self._gy, self._gw, self._gh = geo.x(), geo.y(), geo.width(), geo.height()

        self.setGeometry(self._gx, self._gy, self._gw, self._gh)

        sy1 = int(self._gh * _SEARCH_Y[0])
        sy2 = int(self._gh * _SEARCH_Y[1])

        self._boxes = []
        for i, (xf1, xf2) in enumerate(_CARD_X):
            x1 = int(self._gw * xf1)
            x2 = int(self._gw * xf2)
            box = self._make_box(i, x1, sy1, x2 - x1, sy2 - sy1)
            self._boxes.append(box)

        done_btn = QPushButton("Save & Close", self)
        done_btn.setStyleSheet(
            "background: #1a1a2e; color: #00ff88; border: 2px solid #00ff88;"
            "padding: 8px 20px; font-size: 13pt; font-weight: bold; border-radius: 6px;"
        )
        done_btn.adjustSize()
        done_btn.move(20, 20)
        done_btn.clicked.connect(self._save)

        hint = QLabel("Drag boxes onto card name banners. Resize from edges.", self)
        hint.setStyleSheet(
            "color: white; font-size: 11pt; background: rgba(0,0,0,170); padding: 4px 12px; border-radius: 4px;"
        )
        hint.adjustSize()
        hint.move(20, done_btn.height() + 32)

    def _make_box(self, idx: int, x: int, y: int, w: int, h: int) -> QWidget:
        color = self._COLORS[idx]
        box = QWidget(self)
        box.setGeometry(x, y, w, h)
        box._color = color
        box._drag_offset = None
        box._resize_edge = None
        box._start_geo = None
        box._start_mouse = None

        def paint(e, b=box):
            from PyQt6.QtGui import QPainter, QColor, QPen, QFont
            p = QPainter(b)
            fill = QColor(b._color)
            fill.setAlpha(45)
            p.fillRect(b.rect(), fill)
            pen = QPen(QColor(b._color), 3)
            p.setPen(pen)
            p.drawRect(1, 1, b.width() - 3, b.height() - 3)
            p.setPen(QColor("white"))
            f = QFont(); f.setPointSize(11); f.setBold(True)
            p.setFont(f)
            p.drawText(b.rect(), Qt.AlignmentFlag.AlignCenter, f"Card {idx + 1}")

        def _edge(pos, b=box):
            m, x_, y_, w_, h_ = 12, pos.x(), pos.y(), b.width(), b.height()
            r = abs(x_ - w_) < m; bot = abs(y_ - h_) < m
            l = x_ < m;           top = y_ < m
            if r and bot: return "br"
            if l and top: return "tl"
            if r: return "r"
            if bot: return "b"
            if l: return "l"
            if top: return "t"
            return None

        def press(e, b=box):
            if e.button() != Qt.MouseButton.LeftButton: return
            b._resize_edge  = _edge(e.position().toPoint())
            b._drag_offset  = e.globalPosition().toPoint() - b.pos()
            b._start_geo    = b.geometry()
            b._start_mouse  = e.globalPosition().toPoint()

        def move(e, b=box):
            pos = e.position().toPoint()
            if not (b._drag_offset or b._resize_edge):
                cursors = {"br":"SizeFDiagCursor","tl":"SizeFDiagCursor",
                           "r":"SizeHorCursor","l":"SizeHorCursor",
                           "b":"SizeVerCursor","t":"SizeVerCursor"}
                c = cursors.get(_edge(pos), "SizeAllCursor")
                b.setCursor(getattr(Qt.CursorShape, c))
                return
            gp = e.globalPosition().toPoint()
            if b._resize_edge:
                from PyQt6.QtCore import QRect
                dx = gp.x() - b._start_mouse.x()
                dy = gp.y() - b._start_mouse.y()
                g = QRect(b._start_geo)
                ed = b._resize_edge
                if "r" in ed: g.setRight(g.right() + dx)
                if "b" in ed: g.setBottom(g.bottom() + dy)
                if "l" in ed: g.setLeft(g.left() + dx)
                if "t" in ed: g.setTop(g.top() + dy)
                if g.width() > 20 and g.height() > 8:
                    b.setGeometry(g)
            elif b._drag_offset:
                b.move(gp - b._drag_offset)
            b.update()

        def release(e, b=box):
            b._drag_offset = None
            b._resize_edge = None

        box.paintEvent        = paint
        box.mousePressEvent   = press
        box.mouseMoveEvent    = move
        box.mouseReleaseEvent = release
        box.setCursor(Qt.CursorShape.SizeAllCursor)
        return box

    def paintEvent(self, e):
        from PyQt6.QtGui import QPainter, QColor
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 55))

    def _save(self):
        from card_ocr import save_zones
        gw, gh = self._gw, self._gh
        card_x = []
        for box in self._boxes:
            g = box.geometry()
            card_x.append((round(g.left() / gw, 4), round(g.right() / gw, 4)))
        tops    = [b.geometry().top()    for b in self._boxes]
        bottoms = [b.geometry().bottom() for b in self._boxes]
        search_y = (round(min(tops) / gh, 4), round(max(bottoms) / gh, 4))
        save_zones(card_x, search_y)
        self.zones_saved.emit()
        self.close()


class CardRewardOverlay(QWidget):
    """Full-screen transparent always-on-top overlay showing card reward stats.

    Completely click-through — all mouse events fall through to the game.
    Three small panels are positioned above each card's name banner.
    """

    # Card x-centres and panel y-band as fractions of the primary screen.
    # x values are midpoints of the OCR banner regions in card_ocr._CARD_X.
    _CX = [0.371, 0.507, 0.643]
    _PY_BOTTOM = 0.40        # panel bottom as fraction of game height
    _PW_FRAC = 0.076         # panel width as fraction of game width (~195px at 2560)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        geo = QApplication.primaryScreen().geometry()
        self.setGeometry(geo)

        self._panels: list[QFrame] = []
        self._name_labels:       list[QLabel] = []
        self._wr_with_labels:    list[QLabel] = []
        self._wr_without_labels: list[QLabel] = []
        self._avg_copies_labels: list[QLabel] = []
        self._delta_labels:      list[QLabel] = []

        for _ in range(3):
            panel = QFrame(self)
            panel.setStyleSheet(
                "QFrame { background: rgba(10,15,30,185); border-radius: 6px; }"
            )
            vl = QVBoxLayout(panel)
            vl.setContentsMargins(6, 2, 6, 2)
            vl.setSpacing(0)
            lbls = [QLabel() for _ in range(5)]
            for lbl in lbls:
                lbl.setStyleSheet("background: transparent;")
                font = lbl.font()
                font.setPointSize(13)
                lbl.setFont(font)
                vl.addWidget(lbl)
            self._panels.append(panel)
            self._name_labels.append(lbls[0])
            self._wr_with_labels.append(lbls[1])
            self._wr_without_labels.append(lbls[2])
            self._avg_copies_labels.append(lbls[3])
            self._delta_labels.append(lbls[4])

    def showEvent(self, event):
        super().showEvent(event)
        # Ensure Windows treats this window as click-through even if Qt's flag
        # isn't sufficient on its own.
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | 0x80000 | 0x20  # WS_EX_LAYERED | WS_EX_TRANSPARENT
            )
        except Exception:
            pass

    def _place_panels(self):
        from PyQt6.QtGui import QFontMetrics, QFont
        from card_ocr import get_game_window_rect
        game_rect = get_game_window_rect()
        if game_rect:
            gx, gy, gw, gh = game_rect
        else:
            geo = QApplication.primaryScreen().geometry()
            gx, gy, gw, gh = geo.x(), geo.y(), geo.width(), geo.height()
        y_bottom = gy + int(gh * self._PY_BOTTOM)
        pw = max(150, int(gw * self._PW_FRAC))
        f = QFont()
        f.setPointSize(13)
        line_h = QFontMetrics(f).height()
        ph = line_h * 5 + 8
        for i, cx_frac in enumerate(self._CX):
            cx = gx + int(gw * cx_frac)
            self._panels[i].setGeometry(cx - pw // 2, y_bottom - ph, pw, ph)

    def update_results(self, ocr_results: list, card_stats: dict):
        """Show/update panels from OCR results. ocr_results = [(card_id|None, raw), ...]"""
        self._place_panels()
        if not ocr_results or not any(cid for cid, _ in ocr_results):
            self.hide()
            return

        valid_deltas = [
            card_stats[cid]["win_delta"]
            for cid, _ in ocr_results
            if cid and cid in card_stats and card_stats[cid]["win_delta"] is not None
        ]
        best_delta = max(valid_deltas) if valid_deltas else None

        def _lbl(color, bold=False):
            return f"color: {color}; background: transparent;" + (" font-weight: bold;" if bold else "")

        any_visible = False
        for i, (card_id, _) in enumerate(ocr_results):
            if not card_id:
                self._panels[i].setVisible(False)
                continue

            s = card_stats.get(card_id)

            from parser import fmt_card
            self._name_labels[i].setText(fmt_card(card_id))
            self._name_labels[i].setStyleSheet(_lbl("#ffffff", bold=True))

            if s and s["with_wr"] is not None:
                wr = s["with_wr"]
                wr_color = WIN_COLOR if wr >= 0.5 else LOSS_COLOR
                self._wr_with_labels[i].setText(f"WR With:  {wr*100:.0f}%  ({s['with_runs']})")
                self._wr_with_labels[i].setStyleSheet(_lbl(wr_color))

                wor = s["without_wr"]
                if wor is not None:
                    wor_color = WIN_COLOR if wor >= 0.5 else LOSS_COLOR
                    self._wr_without_labels[i].setText(f"WR W/out: {wor*100:.0f}%  ({s['without_runs']})")
                    self._wr_without_labels[i].setStyleSheet(_lbl(wor_color))
                else:
                    self._wr_without_labels[i].setText("WR W/out: —")
                    self._wr_without_labels[i].setStyleSheet(_lbl(MUTED))

                avg = s["avg_copies_per_run"]
                avg_color = WIN_COLOR if (avg or 0) >= 1.5 else (ACCENT2 if (avg or 0) > 1.0 else MUTED)
                self._avg_copies_labels[i].setText(f"Avg:   {f'{avg:.2f}×' if avg else '—'} in deck")
                self._avg_copies_labels[i].setStyleSheet(_lbl(avg_color))

                delta = s["win_delta"]
                if delta is not None:
                    sign = "+" if delta > 0 else ""
                    is_best = best_delta is not None and abs(delta - best_delta) < 0.001
                    d_color = WIN_COLOR if delta > 0.05 else (LOSS_COLOR if delta < -0.05 else MUTED)
                    self._delta_labels[i].setText(f"Δ:     {sign}{delta*100:.1f}pp" + (" ★" if is_best else ""))
                    self._delta_labels[i].setStyleSheet(_lbl(d_color, bold=is_best))
                else:
                    self._delta_labels[i].setText("Δ:     —")
                    self._delta_labels[i].setStyleSheet(_lbl(MUTED))
            else:
                self._wr_with_labels[i].setText("No history yet")
                self._wr_with_labels[i].setStyleSheet(_lbl(MUTED))
                self._wr_without_labels[i].setText("")
                self._avg_copies_labels[i].setText("")
                self._delta_labels[i].setText("")

            self._panels[i].setVisible(True)
            any_visible = True

        if any_visible:
            self.show()
        else:
            self.hide()

    def hide_overlay(self):
        self.hide()


class MainWindow(QMainWindow):
    REFRESH_MS = 30_000

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Slay the Spire 2 — Run Tracker")
        self.resize(1200, 750)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._build_header())

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setHandleWidth(2)

        self.tabs = QTabWidget()
        self.active_run_tab = ActiveRunTab()
        self.overview_tab = OverviewTab()
        self.run_history_tab = RunHistoryTab()
        self.card_stats_tab = CardStatsTab()
        self.card_rankings_tab = CardRankingsTab()
        self.relic_stats_tab = RelicStatsTab()
        self.tabs.addTab(self.active_run_tab, "⚔ Active Run")
        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.run_history_tab, "Run History")
        self.tabs.addTab(self.card_stats_tab, "Card Stats")
        self.tabs.addTab(self.card_rankings_tab, "Card Rankings")
        self.tabs.addTab(self.relic_stats_tab, "Relic Stats")
        content.addWidget(self.tabs)

        self.right_stack = QStackedWidget()
        self.detail_panel = RunDetailPanel()
        self.card_preview = CardPreviewPanel()
        self.right_stack.addWidget(self.detail_panel)   # index 0
        self.right_stack.addWidget(self.card_preview)   # index 1
        content.addWidget(self.right_stack)
        content.setSizes([750, 400])
        main_layout.addWidget(content)

        self.run_history_tab.run_selected.connect(self.detail_panel.show_run)
        self.card_stats_tab.card_selected.connect(self._on_card_selected)
        self.card_rankings_tab.card_selected.connect(self._on_card_selected)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabs.currentIndex())

        self._overlay = CardRewardOverlay()
        self.active_run_tab.ocr_updated.connect(self._on_ocr_updated)

        self._settings = QSettings("sts2tracker", "sts2tracker")
        ocr_on = self._settings.value("ocr_enabled", True, type=bool)
        self.ocr_toggle_btn.setChecked(ocr_on)
        self._apply_ocr_toggle(ocr_on)

        self._save_path: Path | None = None
        self._loader: RunLoader | None = None
        self._all_runs: list[RunSummary] = []

        detected = find_default_save_path()
        if detected:
            self._load_from(detected)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._reload)
        self._timer.start(self.REFRESH_MS)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet(f"background: {PANEL_BG}; border-bottom: 2px solid {ACCENT};")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 8, 16, 8)
        row.addWidget(make_label("⚔  Slay the Spire 2 Tracker", bold=True, size=16, color=ACCENT))
        row.addStretch()

        self.path_label = make_label("No save folder loaded", color=MUTED)
        row.addWidget(self.path_label)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setStyleSheet(f"background: {CARD_BG}; color: {TEXT}; border: none; padding: 5px 14px; border-radius: 4px;")
        self.browse_btn.clicked.connect(self._browse)
        row.addWidget(self.browse_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet(f"background: {ACCENT2}; color: white; border: none; padding: 5px 14px; border-radius: 4px;")
        self.refresh_btn.clicked.connect(self._reload)
        row.addWidget(self.refresh_btn)

        self.zones_btn = QPushButton("OCR Zones")
        self.zones_btn.setStyleSheet(f"background: {CARD_BG}; color: #00ff88; border: 1px solid #00ff88; padding: 5px 14px; border-radius: 4px;")
        self.zones_btn.clicked.connect(self._show_zone_calibration)
        row.addWidget(self.zones_btn)

        self.ocr_toggle_btn = QPushButton("Card OCR: ON")
        self.ocr_toggle_btn.setCheckable(True)
        self.ocr_toggle_btn.setChecked(True)
        self.ocr_toggle_btn.setStyleSheet(
            f"background: {CARD_BG}; color: #00ff88; border: 1px solid #00ff88; padding: 5px 14px; border-radius: 4px;"
        )
        self.ocr_toggle_btn.toggled.connect(self._toggle_ocr)
        row.addWidget(self.ocr_toggle_btn)
        return header

    def _on_tab_changed(self, idx: int):
        widget = self.tabs.widget(idx)
        if widget in (self.card_stats_tab, self.card_rankings_tab):
            self.right_stack.setCurrentIndex(1)
            self.right_stack.setVisible(True)
        elif widget is self.run_history_tab:
            self.right_stack.setCurrentIndex(0)
            self.right_stack.setVisible(True)
        else:
            self.right_stack.setVisible(False)

    def _toggle_ocr(self, checked: bool) -> None:
        self._settings.setValue("ocr_enabled", checked)
        self._apply_ocr_toggle(checked)

    def _apply_ocr_toggle(self, enabled: bool) -> None:
        self.active_run_tab.set_ocr_enabled(enabled)
        self.zones_btn.setEnabled(enabled)
        if enabled:
            self.ocr_toggle_btn.setText("Card OCR: ON")
            self.ocr_toggle_btn.setStyleSheet(
                f"background: {CARD_BG}; color: #00ff88; border: 1px solid #00ff88; padding: 5px 14px; border-radius: 4px;"
            )
        else:
            self.ocr_toggle_btn.setText("Card OCR: OFF")
            self.ocr_toggle_btn.setStyleSheet(
                f"background: {CARD_BG}; color: {MUTED}; border: 1px solid {MUTED}; padding: 5px 14px; border-radius: 4px;"
            )

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select StS2 history folder", str(self._save_path or Path.home())
        )
        if folder:
            self._load_from(Path(folder))

    def _reload(self):
        if self._save_path:
            self._load_from(self._save_path)

    def _load_from(self, path: Path):
        self._save_path = path
        self.path_label.setText(str(path))
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Loading...")
        self.active_run_tab.set_save_path(path)
        self._loader = RunLoader(path)
        self._loader.done.connect(self._on_loaded)
        self._loader.start()

    def _on_card_selected(self, card_id: str):
        active = self.tabs.currentWidget()
        tab = active if active in (self.card_stats_tab, self.card_rankings_tab) else self.card_stats_tab
        char_f = tab.char_filter.currentText()
        mf = tab.mode_filter
        filtered = filter_runs(self._all_runs, char_f, mf.include_sp, mf.include_mp, mf.include_daily)
        self.card_preview.set_runs(filtered, char_f)
        self.card_preview.show_card(card_id)

    def _show_zone_calibration(self):
        self._calib = ZoneCalibrationOverlay()
        self._calib.zones_saved.connect(lambda: None)  # zones reload on next OCR scan
        self._calib.show()

    def _on_ocr_updated(self, ocr_results: list):
        try:
            if ocr_results:
                self._overlay.update_results(ocr_results, self.active_run_tab._card_stats)
            else:
                self._overlay.hide_overlay()
        except Exception:
            import traceback
            traceback.print_exc()
            self._overlay.hide_overlay()

    def _on_loaded(self, runs: list[RunSummary]):
        self._all_runs = runs
        for tab in (self.overview_tab, self.run_history_tab, self.card_stats_tab,
                    self.card_rankings_tab, self.relic_stats_tab):
            tab.load_runs(runs)
        self.active_run_tab.update_historical_stats(runs)
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh")


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
