"""Spikeless - the small widgets every window uses: fields that ignore the wheel until clicked
into, a colour button, a section that folds, a clickable link."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QColorDialog, QComboBox, QDialog, QHBoxLayout, QLabel,
    QPushButton, QToolButton, QVBoxLayout, QWidget,
)


def pick_color(parent, color) -> str | None:
    """A colour from the dialog (dark like the app), or None if cancelled."""
    # the window, not the button: a ColorButton's style (its colour) would paint the dialog
    dlg = QColorDialog(QColor(color), parent.window() if parent is not None else None)
    dlg.setOption(QColorDialog.DontUseNativeDialog, True)
    dlg.setPalette(QApplication.palette())
    if dlg.exec() != QDialog.Accepted or not dlg.currentColor().isValid():
        return None
    return dlg.currentColor().name()


class _WheelGuard(QObject):
    """A field takes the wheel only once clicked into: scrolling a panel past a spin box
    must not change the plot. The ignored event goes on to the scroll area behind it."""

    def eventFilter(self, obj, ev):                     # noqa: N802 - Qt's name
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            ev.ignore()
            return True
        return False


_GUARD = _WheelGuard()


def guard_fields(root: QWidget) -> None:
    """Every spin box and combo under `root`: no wheel until clicked into, and a typed
    number applied on Enter or leaving the field, not at each key."""
    for w in root.findChildren(QAbstractSpinBox) + root.findChildren(QComboBox):
        # StrongFocus: the default WheelFocus would hand the field focus on the wheel event
        # itself, and the guard would let that same event through.
        w.setFocusPolicy(Qt.StrongFocus)
        w.installEventFilter(_GUARD)
        if isinstance(w, QAbstractSpinBox):
            w.setKeyboardTracking(False)


class ColorButton(QPushButton):
    def __init__(self, color, on_change=None):
        super().__init__(color)
        self.color = color
        self._on_change = on_change
        self._paint()
        self.clicked.connect(self._pick)

    def set_color(self, color):
        self.color = color
        self._paint()

    def _paint(self):
        self.setStyleSheet(f"background:{self.color}; padding:4px;")
        self.setText(self.color)

    def _pick(self):
        c = pick_color(self, self.color)
        if c:
            self.set_color(c)
            if self._on_change:
                self._on_change()


class Collapsible(QWidget):
    """A bold title that folds its content away; `extra`: a widget beside the title."""

    def __init__(self, title, content, expanded=True, extra=None):
        super().__init__()
        self._btn = QToolButton()
        self._btn.setText(title)
        self._btn.setCheckable(True)
        self._btn.setChecked(expanded)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._btn.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self._btn.toggled.connect(self._on_toggled)
        self._content = content
        self._content.setVisible(expanded)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        if extra is None:
            lay.addWidget(self._btn)
        else:
            head = QHBoxLayout()
            head.addWidget(self._btn)
            head.addWidget(extra)
            head.addStretch(1)
            lay.addLayout(head)
        lay.addWidget(self._content)

    def set_title(self, text):
        self._btn.setText(text)

    def _on_toggled(self, on):
        self._content.setVisible(on)
        self._btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


def link(text, icon, color, fn, tip):
    """'text icon', both clickable, the icon in colour (text may be empty)."""
    lab = QLabel((f"<a href='#' style='color:#e0e0e0'>{text}</a> " if text else "")
                 + f"<a href='#' style='color:{color}; text-decoration:none'>{icon}</a>")
    lab.setToolTip(tip)
    lab.linkActivated.connect(lambda _: fn())
    return lab
