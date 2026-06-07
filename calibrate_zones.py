"""Drag the green boxes to align with the card name banners, then press Done."""
import sys
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QPushButton
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QFont

from card_ocr import _CARD_X, _SEARCH_Y, get_game_window_rect

COLORS = ["#00ff00", "#00ccff", "#ff9900"]


class DragBox(QWidget):
    def __init__(self, parent, color, rect: QRect, label: str):
        super().__init__(parent)
        self.color = QColor(color)
        self.label = label
        self.setGeometry(rect)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_offset = None
        self._resize_edge = None

    def paintEvent(self, e):
        p = QPainter(self)
        fill = QColor(self.color)
        fill.setAlpha(40)
        p.fillRect(self.rect(), fill)
        pen = QPen(self.color, 3)
        p.setPen(pen)
        p.drawRect(1, 1, self.width() - 3, self.height() - 3)
        p.setPen(QColor("white"))
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.label)

    def _edge(self, pos):
        m = 12
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        right  = abs(x - w) < m
        bottom = abs(y - h) < m
        left   = x < m
        top    = y < m
        if right and bottom: return "br"
        if left  and top:    return "tl"
        if right:            return "r"
        if bottom:           return "b"
        if left:             return "l"
        if top:              return "t"
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._resize_edge = self._edge(e.position().toPoint())
            self._drag_offset = e.globalPosition().toPoint() - self.pos()
            self._start_geo   = self.geometry()
            self._start_mouse = e.globalPosition().toPoint()

    def mouseReleaseEvent(self, e):
        self._drag_offset  = None
        self._resize_edge  = None

    def mouseMoveEvent(self, e):
        if not (self._drag_offset or self._resize_edge):
            edge = self._edge(e.position().toPoint())
            cursors = {
                "br": Qt.CursorShape.SizeFDiagCursor,
                "tl": Qt.CursorShape.SizeFDiagCursor,
                "r":  Qt.CursorShape.SizeHorCursor,
                "l":  Qt.CursorShape.SizeHorCursor,
                "b":  Qt.CursorShape.SizeVerCursor,
                "t":  Qt.CursorShape.SizeVerCursor,
            }
            self.setCursor(cursors.get(edge, Qt.CursorShape.SizeAllCursor))
        gp = e.globalPosition().toPoint()
        if self._resize_edge:
            dx = gp.x() - self._start_mouse.x()
            dy = gp.y() - self._start_mouse.y()
            g  = QRect(self._start_geo)
            ed = self._resize_edge
            if "r" in ed: g.setRight(g.right() + dx)
            if "b" in ed: g.setBottom(g.bottom() + dy)
            if "l" in ed: g.setLeft(g.left() + dx)
            if "t" in ed: g.setTop(g.top() + dy)
            if g.width() > 20 and g.height() > 10:
                self.setGeometry(g)
        elif self._drag_offset:
            self.move(gp - self._drag_offset)
        self.update()


class CalibrationOverlay(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        game_rect = get_game_window_rect()
        if game_rect:
            self.gx, self.gy, self.gw, self.gh = game_rect
        else:
            geo = QApplication.primaryScreen().geometry()
            self.gx, self.gy, self.gw, self.gh = geo.x(), geo.y(), geo.width(), geo.height()

        self.setGeometry(self.gx, self.gy, self.gw, self.gh)

        sy1 = int(self.gh * _SEARCH_Y[0])
        sy2 = int(self.gh * _SEARCH_Y[1])

        self._boxes: list[DragBox] = []
        for i, (xf1, xf2) in enumerate(_CARD_X):
            x1 = int(self.gw * xf1)
            x2 = int(self.gw * xf2)
            box = DragBox(self, COLORS[i], QRect(x1, sy1, x2 - x1, sy2 - sy1), f"Card {i+1}")
            self._boxes.append(box)

        # Done button
        self._btn = QPushButton("Done — print positions", self)
        self._btn.setStyleSheet(
            "background: #1a1a2e; color: white; border: 2px solid #00ff00;"
            "padding: 8px 18px; font-size: 13pt; border-radius: 6px;"
        )
        self._btn.adjustSize()
        self._btn.move(20, 20)
        self._btn.clicked.connect(self._print_positions)

        # Hint label
        hint = QLabel("Drag boxes to card name banners. Resize from edges. Press Done when aligned.", self)
        hint.setStyleSheet("color: white; font-size: 11pt; background: rgba(0,0,0,160); padding: 4px 10px;")
        hint.adjustSize()
        hint.move(20, self._btn.height() + 30)

    def paintEvent(self, e):
        # dim the whole game area slightly so boxes are visible
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 60))

    def _print_positions(self):
        gw, gh = self.gw, self.gh
        card_x = []
        for box in self._boxes:
            g = box.geometry()
            xf1 = round(g.left()   / gw, 3)
            xf2 = round(g.right()  / gw, 3)
            card_x.append((xf1, xf2))

        # Y from the union of all boxes
        tops    = [b.geometry().top()    for b in self._boxes]
        bottoms = [b.geometry().bottom() for b in self._boxes]
        sy1f = round(min(tops)    / gh, 3)
        sy2f = round(max(bottoms) / gh, 3)

        print("\n===== CALIBRATED POSITIONS =====")
        print(f"_CARD_X = {card_x}")
        print(f"_SEARCH_Y = ({sy1f}, {sy2f})")
        print("================================\n")

        # Also auto-update card_ocr.py
        import re, pathlib
        src = pathlib.Path("card_ocr.py").read_text()
        src = re.sub(
            r"_CARD_X\s*=\s*\[.*?\]",
            f"_CARD_X = {card_x!r}",
            src, flags=re.DOTALL,
        )
        src = re.sub(
            r"_SEARCH_Y\s*=\s*\(.*?\)",
            f"_SEARCH_Y = ({sy1f}, {sy2f})",
            src,
        )
        pathlib.Path("card_ocr.py").write_text(src)
        print("card_ocr.py updated automatically.")
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    w = CalibrationOverlay()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
