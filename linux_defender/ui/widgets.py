"""Reusable widgets: toggle switch, cards, tiles, setting rows."""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QDateTimeEdit, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle,
                               QStyleOptionSpinBox,
                               QVBoxLayout, QWidget)

from linux_defender.ui.icons import svg_pixmap


class Toggle(QAbstractButton):
    def __init__(self, checked=False, parent=None, on="#2fd38a", off="#5b6672"):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._on, self._off = QColor(on), QColor(off)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(44, 24)

    def _animate(self, c):
        self._anim.stop()
        self._anim.setEndValue(1.0 if c else 0.0)
        self._anim.start()

    def _get(self):
        return self._pos

    def _set(self, v):
        self._pos = v
        self.update()

    # NB: must not be called "pos" — that would shadow QWidget.pos and move the widget
    knob = Property(float, _get, _set)

    def set_colors(self, on, off):
        self._on, self._off = QColor(on), QColor(off)
        self.update()

    def paintEvent(self, _):
        # When no animation runs, draw from the real checked state: setChecked() with blocked
        # signals (programmatic sync) must still move the knob.
        if self._anim.state() != QPropertyAnimation.Running:
            self._pos = 1.0 if self.isChecked() else 0.0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        c = QColor(self._off)
        on = self._on
        c.setRedF(c.redF() + (on.redF() - c.redF()) * self._pos)
        c.setGreenF(c.greenF() + (on.greenF() - c.greenF()) * self._pos)
        c.setBlueF(c.blueF() + (on.blueF() - c.blueF()) * self._pos)
        if not self.isEnabled():
            c.setAlphaF(0.45)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.x() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.y() + 3, d, d))


def label(text="", obj=None, wrap=False, muted=False):
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    if muted:
        l.setProperty("muted", True)
    l.setWordWrap(wrap)
    l.setTextInteractionFlags(Qt.TextSelectableByMouse if wrap else Qt.NoTextInteraction)
    return l


def card(obj="Card", margins=18, spacing=10, layout="v"):
    f = QFrame()
    f.setObjectName(obj)
    lay = QVBoxLayout(f) if layout == "v" else QHBoxLayout(f)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return f, lay


def sep():
    f = QFrame()
    f.setObjectName("Sep")
    return f


def button(text, kind=None, icon=None, color="#c9d1d9", on_click=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon:
        b.setIcon(__import__("linux_defender.ui.icons", fromlist=["svg_icon"]).svg_icon(icon, color))
    b.setCursor(Qt.PointingHandCursor)
    if on_click:
        # QPushButton.clicked passes a "checked" bool; never forward it, so handlers with default
        # arguments (lambda k=kind: …) keep their defaults.
        b.clicked.connect(lambda _checked=False: on_click())
    return b


class IconLabel(QLabel):
    def __init__(self, name, color, size=28):
        super().__init__()
        self.setPixmap(svg_pixmap(name, color, size))
        self.setFixedSize(size + 4, size + 4)
        self.setAlignment(Qt.AlignCenter)

    def set_icon(self, name, color, size=28):
        self.setPixmap(svg_pixmap(name, color, size))


class Tile(QFrame):
    """Clickable feature tile."""
    clicked = Signal()

    def __init__(self, icon, title, desc, action_text="Open", color="#2fd38a"):
        super().__init__()
        self.setObjectName("Tile")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 16)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(IconLabel(icon, color, 26))
        top.addStretch(1)
        lay.addLayout(top)
        t = label(title, "H2")
        lay.addWidget(t)
        d = label(desc, wrap=True, muted=True)
        d.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(d)
        lay.addStretch(1)
        self.reason = label("", wrap=True)
        self.reason.setStyleSheet("color:#ffc24b; font-size:9pt;")
        self.reason.setTextInteractionFlags(Qt.NoTextInteraction)
        self.reason.hide()
        lay.addWidget(self.reason)
        self.action = button(action_text, on_click=self.clicked.emit)
        self.action.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lay.addWidget(self.action)
        self.setMinimumHeight(170)
        self._available = True

    def set_available(self, available: bool, reason: str = ""):
        """The whole tile and its button are enabled or disabled together; the reason is shown on the tile."""
        self._available = available
        self.action.setEnabled(available)
        self.setCursor(Qt.PointingHandCursor if available else Qt.ArrowCursor)
        self.setToolTip("" if available else reason)
        self.reason.setText(reason)
        self.reason.setVisible(not available and bool(reason))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._available and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


def fit_field(sb):
    """Give a number/time field enough width for its longest value (maximum, minimum, special text, suffix),
    next to its up/down buttons, so no digit is ever hidden. Returns the field."""
    from linux_defender.ui.style import SPIN_BUTTON_W
    if isinstance(sb, QDateTimeEdit):
        fmt = sb.displayFormat()
        texts = [fmt.replace("HH", "23").replace("hh", "12").replace("mm", "59").replace("ss", "59")
                 .replace("AP", "PM").replace("ap", "pm")]
    else:
        texts = [sb.prefix() + sb.textFromValue(v) + sb.suffix() for v in (sb.minimum(), sb.maximum(), sb.value())]
        if sb.specialValueText():
            texts.append(sb.specialValueText())
    sb.ensurePolished()
    fm = sb.fontMetrics()
    text_w = max(fm.horizontalAdvance(t) for t in texts)
    # space the style takes around the text (padding, border, up/down buttons), measured on a sample width
    opt = QStyleOptionSpinBox()
    sb.initStyleOption(opt)
    opt.rect = QRect(0, 0, 400, max(24, sb.sizeHint().height()))
    edit = sb.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxEditField, sb)
    overhead = 400 - edit.width() if 0 < edit.width() < 400 else 8 + SPIN_BUTTON_W + 2 + 8
    need = text_w + overhead + 4 + 10          # + line-edit margins + room for the caret
    base = sb.property("ld_base_min")
    if base is None:                          # the width the page asked for; fitting only ever adds to it
        base = sb.minimumWidth()
        sb.setProperty("ld_base_min", base)
    sb.setMinimumWidth(max(int(base), need))
    # same height as the line edits and drop-downs next to it (text + 5px padding top/bottom + border)
    sb.setMinimumHeight(max(sb.minimumHeight(), fm.height() + 2 * 5 + 2 + 2))
    return sb


class SettingRow(QWidget):
    """Title + description on the left, a control on the right."""

    def __init__(self, title, desc, control):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 8)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(title, "H2" if False else None))
        if desc:
            d = label(desc, wrap=True, muted=True)
            d.setTextInteractionFlags(Qt.NoTextInteraction)
            col.addWidget(d)
        lay.addLayout(col, 1)
        lay.addSpacing(16)
        if isinstance(control, QAbstractSpinBox):
            fit_field(control)
        lay.addWidget(control, 0, Qt.AlignVCenter | Qt.AlignRight)
        self.control = control
