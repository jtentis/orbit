"""Native tray popover with bounded, state-driven motion."""
from __future__ import annotations
import ctypes
import math
import os
import time
from PySide6.QtCore import (Qt, Signal, Property, QPropertyAnimation, QEasingCurve,
                            QTimer, QRectF, QRect, QPoint)
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QLinearGradient, QPainterPath,
                           QGuiApplication)
from PySide6.QtWidgets import (QWidget, QPushButton, QAbstractButton, QLabel, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QSlider, QComboBox, QStackedWidget,
                               QLineEdit, QScrollArea, QFrame, QApplication, QSizePolicy, QLayout)


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

LABELS = {
    'ac': 'Ar-condicionado', 'lamp': 'Lâmpada',
    'Auto': 'Automático', 'Cool': 'Resfriar', 'Dry': 'Desumidificar', 'Wind': 'Ventilar',
    'Fan': 'Ventilar', 'Heat': 'Aquecer', 'AIComfort': 'Conforto com IA',
    'Low': 'Baixa', 'Mid': 'Média', 'High': 'Alta', 'Turbo': 'Turbo',
    'Fix': 'Parada', 'Up_And_Low': 'Vertical', 'Left_And_Right': 'Horizontal', 'All': 'Todas as direções',
    'Off': 'Normal', 'Sleep': 'Sono', 'Quiet': 'Silencioso', 'Speed': 'Rápido',
    'Nano': 'WindFree', 'NanoSleep': 'WindFree + sono',
}


def label(value):
    return LABELS.get(value, str(value))


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
        # Do not show a confirmed state until the device has read it back.
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

    def configure(self, choices):
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
            button.setAccessibleName(label(code)); button.setToolTip(label(code))
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


class TemperatureReadout(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = None
        self.previous = None
        self.unit = 'C'
        self._progress = 1.
        self.reduced = False
        self.setFixedHeight(61)

    def set_progress(self, value):
        self._progress = value; self.update()
    progress = Property(float, lambda self: self._progress, set_progress)

    def set_value(self, value, unit='C'):
        self.unit = unit
        if value != self.value:
            self.previous, self.value = self.value, value
            self._progress = 0.
            animate(self, b'progress', 1., 180, self.reduced or self.previous is None)
        self.setAccessibleName(f'Temperatura desejada: {value:g} graus {unit}' if value is not None else 'Temperatura indisponível')
        self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont('Segoe UI', 34); font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        if self._progress < 1 and self.previous is not None:
            p.setOpacity(1-self._progress); p.setPen(TEXT)
            p.drawText(QRectF(0, -self._progress*12, self.width(), 61), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f'{self.previous:g}')
        p.setOpacity(self._progress); p.setPen(TEXT)
        value = f'{self.value:g}' if self.value is not None else '—'
        p.drawText(QRectF(0, (1-self._progress)*12, self.width(), 61), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
        offset = p.fontMetrics().horizontalAdvance(value)+6
        p.setOpacity(1); p.setFont(QFont('Segoe UI', 15)); p.setPen(MUTED)
        p.drawText(QRectF(offset, 7, 48, 40), Qt.AlignmentFlag.AlignVCenter, f'°{self.unit}')


class AirConditioner(QWidget):
    """Precise appliance drawing with airflow that follows confirmed operating state."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self._opening = 0.
        self.reduced = False
        self.timer = QTimer(self); self.timer.setInterval(16); self.timer.timeout.connect(self.update)
        self.setFixedHeight(135)
        self.setAccessibleName('Representação do ar-condicionado')

    def set_opening(self, value):
        self._opening = value; self.update()
    opening = Property(float, lambda self: self._opening, set_opening)

    def sync_timer(self):
        if self.isVisible() and self.state and self.state.power and not self.reduced:
            self.timer.start()
        else:
            self.timer.stop()

    def confirm(self, state):
        self.state = state
        animate(self, b'opening', 1. if state and state.power else 0., 250, self.reduced)
        self.sync_timer(); self.update()

    def showEvent(self, event):
        self.sync_timer(); super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop(); super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = min(276., self.width()-22.)
        x = (self.width()-width)/2; y = 12.; height = 66.
        # Shallow, crisp appliance depth; no image download or texture dependency.
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 65))
        p.drawRoundedRect(QRectF(x+3, y+6, width, height), 10, 10)
        gradient = QLinearGradient(0, y, 0, y+height)
        gradient.setColorAt(0, QColor('#fafbfc')); gradient.setColorAt(.6, QColor('#e3e7e9')); gradient.setColorAt(1, QColor('#c5ced2'))
        p.setBrush(gradient); p.drawRoundedRect(QRectF(x, y, width, height), 9, 9)
        p.setPen(QPen(QColor('#ffffff'), 1)); p.drawLine(QPoint(round(x+9), round(y+2)), QPoint(round(x+width-9), round(y+2)))
        p.setPen(QPen(QColor('#aebac0'), .7)); p.drawLine(QPoint(round(x+6), round(y+47)), QPoint(round(x+width-6), round(y+47)))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#253139'))
        p.drawRoundedRect(QRectF(x+12, y+51, width-24, 8+5*self._opening), 3, 3)
        p.setBrush(QColor('#bbc8ce'))
        p.drawRoundedRect(QRectF(x+13, y+51, width-26, 6*(1-self._opening)), 2, 2)
        p.setBrush(QColor('#bac4c8')); p.drawEllipse(QRectF(x+14, y+24, 3, 3))
        p.setPen(QColor('#62727b')); p.setFont(QFont('Segoe UI', 5))
        p.drawText(QRectF(x+26, y+20, 80, 16), Qt.AlignmentFlag.AlignVCenter, 'WindFree')
        if self.state and self.state.power and self.state.display_light:
            p.setPen(QColor('#49aabe')); p.setFont(QFont('Segoe UI', 9))
            target = f'{self.state.temperature:g}' if self.state.temperature is not None else ''
            p.drawText(QRectF(x+width-45, y+18, 30, 18), Qt.AlignmentFlag.AlignRight, target)
        if self.state and self.state.power and not self.reduced:
            fan = str(self.state.fan or '1')
            speed = {'0': .35, '1': .3, '2': .48, '3': .7, '4': .9}.get(fan, .4)
            nano = bool(self.state.windfree)
            clock = time.monotonic()*speed
            count = 22 if not nano else 28
            for i in range(count):
                fraction = (i+.5)/count
                phase = (clock + i*.137) % 1
                start_x = x+20+fraction*(width-40)
                spread = (fraction-.5)*(28 if nano else 45)
                start_y = y+65+phase*42
                opacity = (math.sin(phase*math.pi)**.8)*(.2 if nano else .3)
                color = QColor(150, 207, 224, round(opacity*255))
                p.setPen(QPen(color, .65 if nano else 1., Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                path = QPainterPath(); path.moveTo(start_x+spread*phase, start_y)
                path.cubicTo(start_x+spread*(phase+.2), start_y+7,
                             start_x+spread*(phase+.5), start_y+15,
                             start_x+spread*(phase+.7), min(132., start_y+23))
                p.drawPath(path)


def popup_position(anchor: QRect, available: QRect, width: int, height: int):
    # The tray anchor selects the monitor; its icon/overflow position must not
    # shift the panel. availableGeometry excludes the Windows taskbar.
    return QPoint(max(available.left(), available.right()+1-width),
                  max(available.top(), available.bottom()+1-height))


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


class ControlPanel(QWidget):
    commandRequested = Signal(str, object)
    refreshRequested = Signal()
    searchRequested = Signal()
    connectRequested = Signal(dict)
    startupRequested = Signal(bool)
    motionRequested = Signal(bool)
    quitRequested = Signal()
    logsRequested = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName('ControlPanel'); self.setAccessibleName('Controles de climatização e iluminação')
        self.setStyleSheet(STYLE)
        self.state = None
        self.online = False
        self.busy = False
        self.reduced = not windows_motion_enabled()
        self.pending_temperature = None
        self.sent_temperature = None
        self.active_device = 'ac'
        self._target_position = QPoint()
        self._closing = False
        self.debounce = QTimer(self); self.debounce.setSingleShot(True); self.debounce.setInterval(420)
        self.debounce.timeout.connect(self.commit_temperature)
        self.opacity_animation = QPropertyAnimation(self, b'windowOpacity', self)
        self.opacity_animation.finished.connect(self.animation_finished)
        self.position_animation = QPropertyAnimation(self, b'pos', self)
        root = QVBoxLayout(self); root.setContentsMargins(1, 1, 1, 1); root.setSpacing(0)
        self.scroll = QScrollArea(); self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True); self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget(); self.content.setObjectName('Content')
        self.pages = PageStack()
        self.pages.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        content_layout = QVBoxLayout(self.content); content_layout.setContentsMargins(0, 0, 0, 0)
        selector_row = QHBoxLayout(); selector_row.setContentsMargins(22, 12, 22, 0)
        self.devices = Segmented(); self.devices.setAccessibleName('Dispositivo a controlar')
        self.devices.setFixedHeight(34)
        self.devices.configure([('ac', 'Ar-condicionado'), ('lamp', 'Lâmpada')]); self.devices.confirm('ac')
        self.devices.selected.connect(self.select_device); selector_row.addWidget(self.devices)
        root.addLayout(selector_row)
        content_layout.addWidget(self.pages); self.scroll.setWidget(self.content); root.addWidget(self.scroll)
        self.control_page = self.build_controls()
        self.settings_page = self.build_settings()
        self.pages.addWidget(self.control_page); self.pages.addWidget(self.settings_page)
        from .lamp_ui import LampPage, LampSetup
        from .lamp_local_ui import LocalLampSetup
        self.lamp_page = LampPage(self); self.lamp_setup = LampSetup(self)
        self.pages.addWidget(self.lamp_page); self.pages.addWidget(self.lamp_setup)
        self.lamp_local_setup = LocalLampSetup(self); self.pages.addWidget(self.lamp_local_setup)
        self.lamp_page.render(None, False, False, 'Conta ainda não conectada', {}, False)
        self.lamp_setup.render(False, 'Conta ainda não conectada', False, {})
        self.setFixedWidth(388)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(BORDER, 1)); p.setBrush(BG)
        p.drawRoundedRect(QRectF(.5, .5, self.width()-1, self.height()-1), 16, 16)

    def text(self, value, name=None):
        widget = QLabel(value)
        if name: widget.setObjectName(name)
        return widget

    def separator(self, layout):
        line = QFrame(); line.setFixedHeight(1); line.setStyleSheet(f'background: {SURFACE.name()};')
        layout.addWidget(line)

    def build_controls(self):
        page = QWidget(); page.setObjectName('Page')
        layout = QVBoxLayout(page); layout.setContentsMargins(22, 14, 22, 12); layout.setSpacing(3)
        header = QHBoxLayout(); header.setSpacing(8)
        title_layout = QVBoxLayout(); title_layout.setSpacing(2)
        title_layout.addWidget(self.text('WindFree', 'Title'))
        self.room_label = self.text('Conectando ao aparelho…', 'Small'); title_layout.addWidget(self.room_label)
        header.addLayout(title_layout, 1)
        self.power_button = IconButton('power', 'Ligar aparelho', size=40)
        self.power_button.clicked.connect(lambda: self.request('power', not bool(self.state and self.state.power)))
        header.addWidget(self.power_button)
        self.close_button = IconButton('close', 'Fechar painel', size=30)
        self.close_button.clicked.connect(self.dismiss)
        header.addWidget(self.close_button); layout.addLayout(header)
        self.appliance = AirConditioner(); self.appliance.setFixedHeight(122); layout.addWidget(self.appliance)
        temperature_header = QHBoxLayout()
        temperature_header.addWidget(self.text('Temperatura desejada', 'Section'))
        temperature_header.addStretch()
        self.temperature_hint = self.text('Ligue para ajustar', 'Small'); temperature_header.addWidget(self.temperature_hint)
        layout.addLayout(temperature_header)
        self.readout = TemperatureReadout(); layout.addWidget(self.readout)
        slider_row = QHBoxLayout(); slider_row.setSpacing(12)
        self.minus = IconButton('minus', 'Diminuir temperatura', size=32)
        self.plus = IconButton('plus', 'Aumentar temperatura', size=32)
        self.slider = QSlider(Qt.Orientation.Horizontal); self.slider.setAccessibleName('Temperatura desejada')
        self.slider.setFixedHeight(28)
        self.slider.valueChanged.connect(self.preview_temperature)
        self.slider.sliderReleased.connect(self.schedule_temperature)
        self.minus.clicked.connect(lambda: self.nudge_temperature(-1))
        self.plus.clicked.connect(lambda: self.nudge_temperature(1))
        slider_row.addWidget(self.minus); slider_row.addWidget(self.slider, 1); slider_row.addWidget(self.plus)
        layout.addLayout(slider_row)
        bounds = QHBoxLayout(); bounds.setContentsMargins(44, 0, 44, 0)
        self.minimum_label = self.text('16 °C', 'Small'); self.maximum_label = self.text('30 °C', 'Small')
        bounds.addWidget(self.minimum_label); bounds.addStretch(); bounds.addWidget(self.maximum_label)
        layout.addLayout(bounds)
        layout.addSpacing(3)
        self.mode_label = self.text('Modo', 'Section'); layout.addWidget(self.mode_label)
        self.modes = Segmented(); self.modes.selected.connect(lambda code: self.request('mode', code))
        layout.addWidget(self.modes)
        selectors = QGridLayout(); selectors.setHorizontalSpacing(12); selectors.setVerticalSpacing(5)
        for column, (name, attr, kind) in enumerate([('Ventilação', 'fan_combo', 'fan'), ('Direção do ar', 'swing_combo', 'swing')]):
            selectors.addWidget(self.text(name, 'Section'), 0, column)
            combo = Choice(); combo.setAccessibleName(name)
            combo.activated.connect(lambda index, c=combo, k=kind: self.request(k, c.itemData(index)))
            setattr(self, attr, combo); selectors.addWidget(combo, 1, column)
        layout.addLayout(selectors)
        self.separator(layout)
        self.wind_row, self.wind_toggle = self.toggle_row('wind', 'WindFree', 'Ar suave, sem vento direto')
        self.wind_toggle.clicked.connect(lambda: self.request('windfree', not bool(self.state and self.state.windfree)))
        layout.addWidget(self.wind_row)
        self.light_row, self.light_toggle = self.toggle_row('lamp', 'Luz do display', 'Iluminação do aparelho')
        self.light_toggle.clicked.connect(lambda: self.request('display_light', not bool(self.state and self.state.display_light)))
        layout.addWidget(self.light_row)
        self.separator(layout)
        footer = QHBoxLayout(); footer.setSpacing(8)
        self.status = self.text('Conectando…', 'Small'); self.status.setWordWrap(True)
        self.status.setAccessibleName('Estado da conexão e do envio')
        footer.addWidget(self.status, 1)
        self.refresh_button = IconButton('refresh', 'Atualizar estado', size=30)
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        self.settings_button = IconButton('settings', 'Abrir configurações', size=30)
        self.settings_button.clicked.connect(lambda: self.show_page(1))
        footer.addWidget(self.refresh_button); footer.addWidget(self.settings_button)
        layout.addLayout(footer)
        return page

    def toggle_row(self, icon, title, subtitle):
        row = QWidget(); line = QHBoxLayout(row); line.setContentsMargins(0, 3, 0, 3); line.setSpacing(10)
        symbol = IconButton(icon, title, size=28); symbol.setEnabled(False); symbol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        line.addWidget(symbol)
        text = QVBoxLayout(); text.setSpacing(2); text.addWidget(self.text(title)); text.addWidget(self.text(subtitle, 'Small'))
        line.addLayout(text, 1)
        toggle = Toggle(title); line.addWidget(toggle)
        return row, toggle

    def build_settings(self):
        page = QWidget(); page.setObjectName('Page')
        layout = QVBoxLayout(page); layout.setContentsMargins(22, 18, 22, 18); layout.setSpacing(14)
        heading = QHBoxLayout()
        back = IconButton('back', 'Voltar aos controles', size=30); back.clicked.connect(lambda: self.show_page(0))
        heading.addWidget(back); heading.addWidget(self.text('Configurações', 'Title'), 1)
        close = IconButton('close', 'Fechar painel', size=30); close.clicked.connect(self.dismiss); heading.addWidget(close)
        layout.addLayout(heading); layout.addSpacing(8)
        self.connection_label = self.text('Conexão local', 'Muted'); self.connection_label.setWordWrap(True)
        layout.addWidget(self.connection_label)
        layout.addWidget(self.text('IP do ar-condicionado', 'Section'))
        self.ip_field = QLineEdit(); self.ip_field.setPlaceholderText('Ex.: 192.168.15.13'); self.ip_field.setAccessibleName('IP do ar-condicionado')
        layout.addWidget(self.ip_field)
        self.connect_button = QPushButton('Conectar ao aparelho'); self.connect_button.setObjectName('Primary')
        self.connect_button.clicked.connect(self.manual_connect); self.ip_field.returnPressed.connect(self.manual_connect)
        layout.addWidget(self.connect_button)
        self.search_button = QPushButton('Buscar aparelho na rede'); self.search_button.clicked.connect(self.searchRequested.emit); layout.addWidget(self.search_button)
        self.found_combo = Choice(); self.found_combo.setAccessibleName('Aparelhos encontrados')
        self.found_combo.activated.connect(lambda index: self.connectRequested.emit(self.found_combo.itemData(index)))
        self.found_combo.hide(); layout.addWidget(self.found_combo)
        self.separator(layout)
        startup_row, self.startup_toggle = self.toggle_row('power', 'Iniciar com o Windows', 'Manter o controle na bandeja')
        self.startup_toggle.clicked.connect(lambda: self.startupRequested.emit(not self.startup_toggle.isChecked()))
        layout.addWidget(startup_row)
        motion_row, self.motion_toggle = self.toggle_row('wind', 'Reduzir movimento', 'Transições imediatas e sem fluxo animado')
        self.motion_toggle.clicked.connect(lambda: self.motionRequested.emit(not self.motion_toggle.isChecked()))
        layout.addWidget(motion_row)
        layout.addWidget(self.text('Conforto', 'Section'))
        self.preset_combo = Choice(); self.preset_combo.setAccessibleName('Modo de conforto')
        self.preset_combo.activated.connect(lambda index: self.request('preset', self.preset_combo.itemData(index)))
        layout.addWidget(self.preset_combo)
        self.settings_status = self.text('', 'Small'); self.settings_status.setWordWrap(True); layout.addWidget(self.settings_status)
        layout.addStretch(1)
        logs = QPushButton('Abrir registro de erros'); logs.clicked.connect(self.logsRequested.emit); layout.addWidget(logs)
        quit_button = QPushButton('Sair do WindFree'); quit_button.clicked.connect(self.quitRequested.emit); layout.addWidget(quit_button)
        return page

    def fill_combo(self, combo, choices, selected):
        old = [combo.itemData(i) for i in range(combo.count())]
        if old != [code for code, _ in choices]:
            combo.blockSignals(True); combo.clear()
            for code, caption in choices: combo.addItem(caption, code)
            combo.blockSignals(False)
        combo.setCurrentIndex(combo.findData(selected))

    def render(self, state, online, busy, message, config, startup=False, error=False, operation=None):
        self.state, self.online, self.busy = state, online, busy
        if not busy:
            self.sent_temperature = None
        self.reduced = bool(config.get('reduce_motion', False)) or not windows_motion_enabled()
        for child in self.findChildren(QWidget):
            if hasattr(child, 'reduced'): child.reduced = self.reduced
        self.motion_toggle.confirm(self.reduced); self.startup_toggle.confirm(startup)
        if not self.ip_field.hasFocus(): self.ip_field.setText(config.get('host', ''))
        self.connection_label.setText('Conexão local\n' + config.get('host', 'Aparelho ainda não configurado'))
        enabled = online and not busy
        climate = enabled and bool(state and state.power)
        self.power_button.setEnabled(enabled and bool(state and state.power_writable))
        self.power_button.active = bool(state and state.power and online); self.power_button.update()
        self.power_button.setAccessibleName('Desligar aparelho' if state and state.power else 'Ligar aparelho')
        self.power_button.setToolTip(self.power_button.accessibleName())
        self.refresh_button.setEnabled(not busy)
        for widget in (self.connect_button, self.search_button, self.found_combo, self.ip_field):
            widget.setEnabled(not busy)
        self.connect_button.setText('Conectando…' if busy and operation == 'connect' else 'Conectar ao aparelho')
        self.search_button.setText('Buscando na rede…' if busy and operation == 'discover' else 'Buscar aparelho na rede')
        for widget in (self.slider, self.minus, self.plus, self.modes, self.fan_combo, self.swing_combo, self.preset_combo):
            widget.setEnabled(climate)
        self.wind_toggle.setEnabled(climate and bool(state and state.windfree is not None))
        self.light_toggle.setEnabled(enabled and bool(state and state.display_light is not None))
        if busy and operation == 'command':
            footer = 'Enviando · aguardando confirmação…'
        elif error:
            footer = message
        elif not online:
            footer = message
        elif self.pending_temperature is not None:
            footer = 'Ajuste preparado · aguardando envio'
        else:
            footer = 'Atualizando leitura…' if busy else 'Conectado · estado confirmado'
        self.status.setText(footer); self.settings_status.setText(footer)
        color = ERROR if error else (ACCENT if busy and operation == 'command' else SUBTLE)
        self.status.setStyleSheet(f'color: {color.name()}; font-size: 11px;')
        self.settings_status.setStyleSheet(f'color: {color.name()}; font-size: 11px;')
        if not state:
            self.readout.set_value(None); self.room_label.setText('Sem leitura do aparelho'); self.appliance.confirm(None)
            return
        if online:
            self.room_label.setText(f'Ambiente {state.current:g} °{state.unit} · {"Ligado" if state.power else "Desligado"}' if state.current is not None else ('Ligado' if state.power else 'Desligado'))
        else:
            self.room_label.setText('Sem conexão · mostrando a última leitura')
        self.appliance.confirm(state if online else None)
        self.temperature_hint.setText('Ligue para ajustar' if not state.power else ('Enviando…' if busy and operation == 'command' else ''))
        if not self.slider.isSliderDown() and self.pending_temperature is None and self.sent_temperature is None:
            self.slider.blockSignals(True)
            self.slider.setRange(0, max(0, round((state.maximum-state.minimum)/state.step)))
            self.slider.setValue(round((state.temperature-state.minimum)/state.step) if state.temperature is not None else 0)
            self.slider.blockSignals(False); self.readout.set_value(state.temperature, state.unit)
        self.minimum_label.setText(f'{state.minimum:g} °{state.unit}'); self.maximum_label.setText(f'{state.maximum:g} °{state.unit}')
        short = {'Auto': 'Auto', 'Cool': 'Resfriar', 'Dry': 'Secar', 'Wind': 'Ventilar'}
        self.modes.configure([(code, short.get(code, label(code))) for code in state.modes]); self.modes.confirm(state.mode)
        self.fill_combo(self.fan_combo, [(code, label(name)) for code, name in state.fans], state.fan)
        self.fill_combo(self.swing_combo, [(code, label(code)) for code in state.swings], state.swing)
        self.fill_combo(self.preset_combo, [(code, label(code)) for code in state.presets], state.preset)
        self.wind_row.setVisible(state.windfree is not None); self.light_row.setVisible(state.display_light is not None)
        self.wind_toggle.confirm(state.windfree); self.light_toggle.confirm(state.display_light)

    def preview_temperature(self, tick):
        if not self.state or not self.slider.isEnabled(): return
        self.pending_temperature = round(self.state.minimum+tick*self.state.step, 2)
        self.readout.set_value(self.pending_temperature, self.state.unit)
        self.slider.setAccessibleDescription(f'{self.pending_temperature:g} graus {self.state.unit}; use as setas para ajustar.')
        self.status.setText('Solte para enviar o ajuste' if self.slider.isSliderDown() else 'Preparando o ajuste…')
        if not self.slider.isSliderDown(): self.schedule_temperature()

    def schedule_temperature(self):
        if self.pending_temperature is not None: self.debounce.start()

    def nudge_temperature(self, direction):
        self.slider.setValue(self.slider.value()+direction)

    def commit_temperature(self):
        value = self.pending_temperature
        self.pending_temperature = None
        if self.state and self.online and not self.busy and value is not None and value != self.state.temperature:
            self.sent_temperature = value
            self.commandRequested.emit('temperature', value)
        elif self.state:
            self.readout.set_value(self.state.temperature, self.state.unit)

    def request(self, kind, value):
        if not self.online or self.busy: return
        self.debounce.stop(); self.pending_temperature = None
        self.commandRequested.emit(kind, value)

    def manual_connect(self):
        from .discovery import validate_host
        try:
            host = validate_host(self.ip_field.text())
        except ValueError:
            self.settings_status.setText('Informe um IP válido da sua rede local.')
            self.settings_status.setStyleSheet(f'color: {ERROR.name()}; font-size: 11px;')
            self.ip_field.setFocus()
            return
        self.connectRequested.emit({'host': host})

    def set_found(self, devices):
        self.found_combo.clear()
        for info in devices:
            self.found_combo.addItem(f'{info["name"]} · {info["host"]}', info)
        self.found_combo.setVisible(bool(devices)); self.found_combo.setCurrentIndex(-1)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.scroll.verticalScrollBar().setValue(0)
        if not self.reduced:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            page = self.pages.currentWidget(); effect = QGraphicsOpacityEffect(page); page.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b'opacity', page)
            animation.setStartValue(.4); animation.setEndValue(1.); animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.Type.OutQuart)
            animation.finished.connect(lambda: page.setGraphicsEffect(None))
            self._page_animation = animation; animation.start()
        if index == 1: self.ip_field.setFocus()
        elif index == 3: self.lamp_setup.token.setFocus()
        elif index == 4: self.lamp_local_setup.search.setFocus()
        elif index == 2:
            (self.lamp_page.power if self.lamp_page.power.isEnabled() else self.lamp_page.connect_button).setFocus()
        else: self.power_button.setFocus()

    def select_device(self, code):
        self.active_device = code; self.devices.confirm(code)
        self.show_page(2 if code == 'lamp' else 0)

    def render_lamp(self, state, online, busy, message, info, configured, error=False, operation=None, cloud_configured=None):
        self.lamp_page.render(state, online, busy, message, info, configured, error, operation)
        self.lamp_setup.render(busy, message, configured if cloud_configured is None else cloud_configured, info, error, operation)
        self.lamp_local_setup.render(busy, message, info, error, operation)

    def toggle_at(self, anchor):
        if self.isVisible():
            self.dismiss(); return
        self.pages.setCurrentIndex(2 if self.active_device == 'lamp' else 0)
        if anchor.isNull():
            from PySide6.QtGui import QCursor
            anchor = QRect(QCursor.pos(), QCursor.pos())
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        self.setFixedHeight(min(650, available.height()-24))
        target = popup_position(anchor, available, self.width(), self.height())
        self._target_position = target; self._closing = False
        self.opacity_animation.stop(); self.position_animation.stop()
        self.setWindowOpacity(1. if self.reduced else 0.)
        self.move(target if self.reduced else target-QPoint(0, 10))
        self.show(); self.raise_(); self.activateWindow()
        (self.lamp_page.power if self.active_device == 'lamp' else self.power_button).setFocus()
        if not self.reduced:
            self.opacity_animation.setDuration(220); self.opacity_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
            self.opacity_animation.setStartValue(0.); self.opacity_animation.setEndValue(1.)
            self.position_animation.setDuration(220); self.position_animation.setEasingCurve(QEasingCurve.Type.OutQuart)
            self.position_animation.setStartValue(self.pos()); self.position_animation.setEndValue(target)
            self.opacity_animation.start(); self.position_animation.start()

    def dismiss(self):
        self.lamp_page.commit()
        self.debounce.stop()
        if self.pending_temperature is not None:
            self.commit_temperature()
        if self.reduced or not self.isVisible():
            self.hide(); return
        self._closing = True; self.opacity_animation.stop(); self.position_animation.stop()
        self.opacity_animation.setDuration(150); self.opacity_animation.setStartValue(self.windowOpacity()); self.opacity_animation.setEndValue(0.)
        self.opacity_animation.start()

    def animation_finished(self):
        if self._closing:
            self.hide(); self._closing = False; self.setWindowOpacity(1.)

    def hideEvent(self, event):
        self.lamp_page.commit()
        self.debounce.stop()
        if self.pending_temperature is not None:
            self.commit_temperature()
        self.opacity_animation.stop(); self.position_animation.stop()
        self.appliance.timer.stop()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.pages.currentIndex() in (1, 3, 4): self.show_page(2 if self.active_device == 'lamp' else 0)
            else: self.dismiss()
        else: super().keyPressEvent(event)
