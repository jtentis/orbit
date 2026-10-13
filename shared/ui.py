from __future__ import annotations
import ctypes
import math
import os
from PySide6.QtCore import Qt, Signal, Property, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QWidget, QPushButton, QAbstractButton, QVBoxLayout, QHBoxLayout, QComboBox


def oklch(lightness, chroma, hue):
    angle = math.radians(hue)
    a, b = chroma * math.cos(angle), chroma * math.sin(angle)
    l = (lightness + .3963377774 * a + .2158037573 * b) ** 3
    m = (lightness - .1055613458 * a - .0638541728 * b) ** 3
    s = (lightness - .0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (4.0767416621*l - 3.3077115913*m + .2309699292*s,
           -1.2684380046*l + 2.6097574011*m - .3413193965*s,
           -.0041960863*l - .7034186147*m + 1.7076147010*s)
    def channel(v):
        v = min(1, max(0, v))
        return round(255 * (12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055))
    return QColor(*(channel(v) for v in rgb))


BG = oklch(.19, .012, 245)


SURFACE = oklch(.245, .013, 245)


CONTROL = oklch(.30, .016, 245)


TEXT = oklch(.96, .004, 245)


MUTED = oklch(.75, .013, 245)


SUBTLE = oklch(.64, .015, 245)


ACCENT = QColor('#36b9e8')


INK = QColor('#072b3b')


BORDER = oklch(.35, .016, 245)


ERROR = QColor('#ffb2a6')


def windows_motion_enabled():
    if os.name != 'nt':
        return True
    value = ctypes.c_int(1)
    if not ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0):
        return True
    return bool(value.value)


def animate(owner, property_name, target, duration=180, reduced=False):
    name = property_name.decode()
    animations = getattr(owner, '_animations', {})
    previous = animations.pop(name, None)
    if previous:
        previous.stop()
        previous.deleteLater()
    if owner.property(name) == target:
        return
    if reduced or not owner.isVisible():
        owner.setProperty(name, target)
        return
    animation = QPropertyAnimation(owner, property_name, owner)
    animation.setStartValue(owner.property(name))
    animation.setEndValue(target)
    animation.setDuration(duration)
    animation.setEasingCurve(QEasingCurve.Type.OutQuart)
    animations[name] = animation
    owner._animations = animations
    animation.start()


def draw_icon(painter, name, rect, color=TEXT, width=1.6):
    painter.save()
    painter.translate(rect.center())
    painter.scale(rect.width()/24, rect.height()/24)
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if name == 'power':
        painter.drawArc(QRectF(-8, -8, 16, 16), 135*16, 270*16)
        painter.drawLine(0, -10, 0, 0)
    elif name == 'snow':
        for angle in (0, 60, 120):
            painter.save(); painter.rotate(angle)
            painter.drawLine(0, -9, 0, 9)
            for y in (-6, 6):
                direction = 1 if y > 0 else -1
                painter.drawLine(0, y, -3, y-direction*3)
                painter.drawLine(0, y, 3, y-direction*3)
            painter.restore()
    elif name in ('wind', 'fan'):
        for y, right in ((-5, 7), (0, 10), (5, 5)):
            path = QPainterPath(); path.moveTo(-9, y); path.lineTo(right-3, y)
            path.cubicTo(right+3, y, right+3, y-7, right-1, y-7)
            painter.drawPath(path)
    elif name == 'lamp':
        painter.drawEllipse(QRectF(-6, -9, 12, 12))
        painter.drawLine(-3, 3, -3, 6); painter.drawLine(3, 3, 3, 6)
        painter.drawLine(-3, 6, 3, 6); painter.drawLine(-2, 9, 2, 9)
    elif name == 'settings':
        for x, y in ((-7, -4), (0, 5), (7, -2)):
            painter.drawLine(x, -9, x, 9)
            painter.setBrush(BG); painter.drawEllipse(QRectF(x-2.5, y-2.5, 5, 5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
    elif name == 'refresh':
        painter.drawArc(QRectF(-8, -8, 16, 16), 45*16, 290*16)
        painter.drawLine(6, -7, 6, -1); painter.drawLine(6, -1, 0, -1)
    elif name == 'close':
        painter.drawLine(-5, -5, 5, 5); painter.drawLine(-5, 5, 5, -5)
    elif name == 'back':
        painter.drawLine(-6, 0, 6, 0); painter.drawLine(-6, 0, 0, -6); painter.drawLine(-6, 0, 0, 6)
    elif name == 'check':
        painter.drawLine(-7, 0, -2, 5); painter.drawLine(-2, 5, 8, -6)
    elif name in ('minus', 'plus'):
        painter.drawLine(-6, 0, 6, 0)
        if name == 'plus':
            painter.drawLine(0, -6, 0, 6)
    painter.restore()


class ActionButton(QAbstractButton):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click(); event.accept()
        else:
            super().keyPressEvent(event)


class IconButton(ActionButton):
    def __init__(self, icon, accessible, parent=None, size=36):
        super().__init__(parent)
        self.icon_name = icon
        self.active = False
        self._hover = 0.
        self.reduced = False
        self.setFixedSize(size, size)
        self.setAccessibleName(accessible)
        self.setToolTip(accessible)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_hover(self, value):
        self._hover = value; self.update()
    hover = Property(float, lambda self: self._hover, set_hover)

    def enterEvent(self, event):
        animate(self, b'hover', 1., 140, self.reduced)
        super().enterEvent(event)

    def leaveEvent(self, event):
        animate(self, b'hover', 0., 140, self.reduced)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.width()
        if self.active:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(ACCENT)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            color = QColor(CONTROL); color.setAlphaF(.45 + .35*self._hover)
            p.setBrush(color)
        inset = 2 if self.isDown() else 0
        p.drawRoundedRect(QRectF(inset, inset, size-inset*2, size-inset*2), 10, 10)
        color = INK if self.active else (TEXT if self.isEnabled() else SUBTLE)
        draw_icon(p, self.icon_name, QRectF(size/2-10, size/2-10, 20, 20), color)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(ACCENT, 1.5))
            p.drawRoundedRect(QRectF(1, 1, size-2, size-2), 10, 10)


class Toggle(ActionButton):
    def __init__(self, accessible, parent=None):
        super().__init__(parent)
        self._position = 0.
        self.reduced = False
        self.setFixedSize(48, 28)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(accessible)

    def set_position(self, value):
        self._position = value; self.update()
    position = Property(float, lambda self: self._position, set_position)

    def confirm(self, value):
        self.setChecked(bool(value))
        animate(self, b'position', 1. if value else 0., 180, self.reduced)

    def nextCheckState(self):
# Selection follows readback, not clicks.
        pass

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._position
        base = CONTROL
        color = QColor(*(round(base.getRgb()[i]*(1-t)+ACCENT.getRgb()[i]*t) for i in range(3)))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
        p.drawRoundedRect(QRectF(1, 2, 46, 24), 12, 12)
        p.setBrush(TEXT if self.isEnabled() else SUBTLE)
        p.drawEllipse(QRectF(4+20*t, 5, 18, 18))
        if self.hasFocus():
            p.setPen(QPen(ACCENT, 1.3)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(.7, .7, 46.6, 26.6), 13, 13)


class Segmented(QWidget):
    selected = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.codes = []
        self.buttons = []
        self.current = -1
        self._position = 0.
        self.reduced = False
        self.setFixedHeight(42)
        self.layout_ = QHBoxLayout(self); self.layout_.setContentsMargins(3, 3, 3, 3); self.layout_.setSpacing(0)

    def set_position(self, value):
        self._position = value; self.update()
    position = Property(float, lambda self: self._position, set_position)

    def configure(self, choices, labels=None):
        codes = [code for code, _ in choices]
        if codes == self.codes:
            return
        self.codes = codes
        while self.layout_.count():
            item = self.layout_.takeAt(0); item.widget().deleteLater()
        self.buttons = []
        for code, caption in choices:
            button = QPushButton(caption)
            button.setObjectName('Segment')
            accessible = (labels or {}).get(code, caption)
            button.setAccessibleName(accessible); button.setToolTip(accessible)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, c=code: self.selected.emit(c))
            self.layout_.addWidget(button, 1); self.buttons.append(button)

    def confirm(self, code):
        self.current = self.codes.index(code) if code in self.codes else -1
        if self.current >= 0:
            animate(self, b'position', float(self.current), 190, self.reduced)
        for i, button in enumerate(self.buttons):
            button.setProperty('selected', i == self.current)
            button.style().unpolish(button); button.style().polish(button)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(SURFACE)
        p.drawRoundedRect(QRectF(self.rect()), 11, 11)
        if self.current >= 0 and self.codes:
            cell = (self.width()-6)/len(self.codes)
            p.setBrush(oklch(.36, .044, 235) if self.isEnabled() else CONTROL)
            p.drawRoundedRect(QRectF(3+self._position*cell, 3, cell, self.height()-6), 8, 8)


class PageStack(QWidget):
    """Only the visible page contributes to layout bounds in the small popup."""
    def __init__(self):
        super().__init__()
        self._pages = []; self._index = 0
        self._layout = QVBoxLayout(self); self._layout.setContentsMargins(0, 0, 0, 0)

    def addWidget(self, widget):
        self._pages.append(widget); self._layout.addWidget(widget)
        widget.setVisible(len(self._pages) == 1)
        return len(self._pages)-1

    def count(self): return len(self._pages)
    def widget(self, index): return self._pages[index]
    def currentIndex(self): return self._index
    def currentWidget(self): return self._pages[self._index] if self._pages else None

    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.currentWidget().minimumSizeHint() if self.currentWidget() else super().minimumSizeHint()

    def setCurrentIndex(self, index):
        if not 0 <= index < len(self._pages): return
        self._index = index
        for i, page in enumerate(self._pages): page.setVisible(i == index)
        self._layout.invalidate()
        self.updateGeometry()


class Choice(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(MUTED if self.isEnabled() else SUBTLE, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        path = QPainterPath(); x, y = self.width()-15, self.height()/2
        path.moveTo(x-3, y-2); path.lineTo(x, y+1); path.lineTo(x+3, y-2); p.drawPath(path)


STYLE = f'''
QWidget {{ color: {TEXT.name()}; font-family: "Segoe UI"; font-size: 13px; }}
QWidget#Page, QWidget#Content, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel#Muted {{ color: {MUTED.name()}; }}
QLabel#Small {{ color: {SUBTLE.name()}; font-size: 11px; }}
QLabel#Title {{ font-size: 17px; font-weight: 600; }}
QLabel#Section {{ color: {MUTED.name()}; font-size: 12px; }}
QPushButton {{ border: none; border-radius: 9px; padding: 8px 12px; background: {CONTROL.name()}; color: {TEXT.name()}; }}
QPushButton:hover {{ background: {BORDER.name()}; }}
QPushButton:pressed {{ background: {SURFACE.name()}; }}
QPushButton:focus, QComboBox:focus, QLineEdit:focus {{ border: 1px solid {ACCENT.name()}; }}
QPushButton:disabled {{ color: {SUBTLE.name()}; background: {SURFACE.name()}; }}
QPushButton#Primary {{ background: {ACCENT.name()}; color: {INK.name()}; font-weight: 600; }}
QPushButton#Segment {{ background: transparent; padding: 0 2px; font-size: 12px; color: {MUTED.name()}; }}
QPushButton#Segment[selected="true"] {{ color: {TEXT.name()}; font-weight: 600; }}
QPushButton#Segment:disabled {{ color: {SUBTLE.name()}; }}
QPushButton#Segment:focus {{ border: 1px solid {ACCENT.name()}; }}
QComboBox, QLineEdit {{ background: {SURFACE.name()}; border: 1px solid {BORDER.name()}; border-radius: 8px; padding: 7px 10px; min-height: 18px; }}
QComboBox:disabled {{ color: {SUBTLE.name()}; border-color: {SURFACE.name()}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ width: 0px; height: 0px; }}
QComboBox QAbstractItemView {{ background: {SURFACE.name()}; color: {TEXT.name()}; border: 1px solid {BORDER.name()}; selection-background-color: {CONTROL.name()}; padding: 4px; }}
QSlider::groove:horizontal {{ height: 6px; background: {CONTROL.name()}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT.name()}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; background: {TEXT.name()}; }}
QSlider::sub-page:horizontal:disabled {{ background: {BORDER.name()}; }}
QSlider::handle:horizontal:disabled {{ background: {SUBTLE.name()}; }}
QSlider:focus {{ border: 1px solid {ACCENT.name()}; border-radius: 7px; }}
QScrollBar:vertical {{ background: transparent; width: 5px; margin: 8px 0; }}
QScrollBar::handle:vertical {{ background: {BORDER.name()}; min-height: 24px; border-radius: 2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
'''
