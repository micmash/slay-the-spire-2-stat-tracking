"""Color palette, Qt stylesheet, and shared tooltip text."""

# ── Palette ──────────────────────────────────────────────────────────
DARK_BG = "#1a1a2e"
PANEL_BG = "#16213e"
CARD_BG = "#0f3460"
ACCENT = "#e94560"
ACCENT2 = "#533483"
WIN_COLOR = "#4caf50"
LOSS_COLOR = "#e94560"
TEXT = "#eaeaea"
MUTED = "#888"

# ── Global stylesheet ────────────────────────────────────────────────
STYLE = f"""
QMainWindow, QWidget {{ background-color: {DARK_BG}; color: {TEXT}; font-family: 'Segoe UI', Arial; }}
QTabWidget::pane {{ border: 1px solid {CARD_BG}; background: {PANEL_BG}; }}
QTabBar::tab {{ background: {PANEL_BG}; color: {MUTED}; padding: 8px 20px; border: none; }}
QTabBar::tab:selected {{ background: {CARD_BG}; color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTableWidget {{ background: {PANEL_BG}; color: {TEXT}; gridline-color: {CARD_BG}; border: none; font-size: 13px; }}
QTableWidget::item {{ padding: 4px 8px; }}
QTableWidget::item:selected {{ background: {ACCENT2}; color: white; }}
QHeaderView::section {{ background: {CARD_BG}; color: {TEXT}; padding: 6px 8px; border: none; font-weight: bold; }}
QPushButton {{ background: {ACCENT}; color: white; border: none; padding: 7px 18px; border-radius: 4px; font-size: 13px; }}
QPushButton:hover {{ background: #c73652; }}
QPushButton.secondary {{ background: {CARD_BG}; }}
QPushButton.secondary:hover {{ background: {ACCENT2}; }}
QComboBox {{ background: {CARD_BG}; color: {TEXT}; border: 1px solid {ACCENT2}; padding: 4px 8px; border-radius: 4px; }}
QComboBox QAbstractItemView {{ background: {CARD_BG}; color: {TEXT}; selection-background-color: {ACCENT2}; }}
QLineEdit {{ background: {CARD_BG}; color: {TEXT}; border: 1px solid {ACCENT2}; padding: 4px 8px; border-radius: 4px; }}
QTextEdit {{ background: {PANEL_BG}; color: {TEXT}; border: 1px solid {CARD_BG}; padding: 6px; border-radius: 4px; }}
QScrollBar:vertical {{ background: {PANEL_BG}; width: 8px; border: none; }}
QScrollBar::handle:vertical {{ background: {CARD_BG}; border-radius: 4px; min-height: 20px; }}
QSplitter::handle {{ background: {CARD_BG}; }}
QLabel {{ color: {TEXT}; }}
"""

# ── Tooltip copy ─────────────────────────────────────────────────────
DELTA_TIP = (
    "Win Δ (Win Delta)\n\n"
    "Only counts runs where the card appeared as a pick choice.\n"
    "Win rate when you took it  minus  win rate when you skipped it.\n"
    "Cards gained without a pick event (starters, events, boss rewards)\n"
    "are excluded so the comparison is always like-for-like.\n\n"
    "  +20pp  →  Much better outcomes when picked — strong pick\n"
    "  +5pp   →  Slight positive — lean towards picking\n"
    "  ~0pp   →  Neutral — situation-dependent\n"
    "  -5pp   →  Negative — skipping tended to go better\n\n"
    "Low sample sizes (shown in parentheses) make this noisy."
)

COPIES_TIP = (
    "Avg Copies\n\n"
    "Average number of times this card was picked per run where it was taken.\n"
    "1.0 = always taken exactly once.\n"
    "1.5 = taken twice roughly half the time.\n\n"
    "High values suggest the card is sought out multiple times (e.g. via shops or events)."
)
