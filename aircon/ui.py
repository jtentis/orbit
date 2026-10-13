from __future__ import annotations
import math
import time
from PySide6.QtCore import Qt, Property, QTimer, QRectF, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient, QPainterPath
from PySide6.QtWidgets import QWidget

from shared.ui import TEXT, MUTED, animate

LABELS = {
    'Auto': 'Automático', 'Cool': 'Resfriar', 'Dry': 'Desumidificar', 'Wind': 'Ventilar',
    'Fan': 'Ventilar', 'Heat': 'Aquecer', 'AIComfort': 'Conforto com IA',
    'Low': 'Baixa', 'Mid': 'Média', 'High': 'Alta', 'Turbo': 'Turbo',
    'Fix': 'Parada', 'Up_And_Low': 'Vertical', 'Left_And_Right': 'Horizontal', 'All': 'Todas as direções',
    'Off': 'Normal', 'Sleep': 'Sono', 'Quiet': 'Silencioso', 'Speed': 'Rápido',
    'Nano': 'WindFree', 'NanoSleep': 'WindFree + sono',
}


def label(value):
    return LABELS.get(value, str(value))


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
