from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


@lru_cache(maxsize=2)
def orbit_icon(online=True):
    source = (Path(__file__).resolve().parents[1] / 'assets' / 'orbit.svg').read_text(encoding='utf-8')
    color = '#36b9e8' if online else '#98a5b3'
    renderer = QSvgRenderer(QByteArray(source.replace('currentColor', color).encode('utf-8')))
    if not renderer.isValid():
        raise RuntimeError('O ícone do aplicativo não pôde ser carregado.')
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        if not online:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#d56c30'))
            painter.drawEllipse(QRectF(size*.72, size*.72, size*.22, size*.22))
        painter.end()
        icon.addPixmap(pixmap)
    return icon
