"""Lighting pages built from the popup's existing tokens and controls."""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal, Property, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSlider, QPushButton, QLineEdit
from shared.ui import BG, SURFACE, BORDER, ACCENT, TEXT, SUBTLE, ERROR, IconButton, Choice, Segmented, animate

from .presets import WHITE_PRESETS, white_preset_value


class BulbScene(QWidget):
    """A short light transition driven only by confirmed status; no idle timers."""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(118)
        self.reduced = False
        self._illumination = 0.
        self.color = QColor('#fff3d5')
        self.setAccessibleName('Representação da lâmpada')

    def set_illumination(self, value):
        self._illumination = value; self.update()

    illumination = Property(float, lambda self: self._illumination, set_illumination)

    def confirm(self, state):
        if state and state.color_mode in ('color', 'rgb', 'hue') and state.hue is not None:
            self.color = QColor.fromHsvF(state.hue/100, (state.saturation or 0)/100, 1)
        elif state and state.color_mode in ('white', 'colorTemperature') and state.kelvin is not None:
            fraction = min(1, max(0, state.kelvin/100 if state.white_unit == '%' else (state.kelvin-2000)/4500))
            self.color = QColor(255, round(186+fraction*69), round(110+fraction*145))
        else:
            self.color = QColor('#fff3d5')
        target = (max(.15, (state.level if state.level is not None else 100)/100)
                  if state and state.power else 0.)
        animate(self, b'illumination', target, 240, self.reduced)
        self.update()

    def hideEvent(self, event):
        for animation in getattr(self, '_animations', {}).values():
            animation.setCurrentTime(animation.duration())
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width()/2, 4)
        if self._illumination:
            glow = QRadialGradient(0, 40, 69)
            tint = QColor(self.color); tint.setAlpha(round(48*self._illumination))
            glow.setColorAt(0, tint); tint.setAlpha(0); glow.setColorAt(1, tint)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(glow)
            painter.drawEllipse(QRectF(-72, -25, 144, 130))
        glass = QPainterPath(); glass.moveTo(-14, 69)
        glass.cubicTo(-15, 57, -30, 48, -30, 32)
        glass.cubicTo(-30, -6, 30, -6, 30, 32)
        glass.cubicTo(30, 48, 15, 57, 14, 69); glass.closeSubpath()
        tint = QColor(self.color if self._illumination else '#a9b4bd')
        painter.setPen(QPen(QColor('#dbe1e5'), 1)); painter.setBrush(tint); painter.drawPath(glass)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#edf1f4'))
        painter.drawRoundedRect(QRectF(-14, 62, 28, 14), 3, 3)
        painter.setBrush(QColor('#596674')); painter.drawRoundedRect(QRectF(-12, 76, 24, 19), 3, 3)
        painter.setPen(QPen(QColor('#86929e'), 1.4))
        for y in (80, 85, 90): painter.drawLine(-10, y, 10, y-2)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#384451')); painter.drawEllipse(QRectF(-6, 94, 12, 5))


class LampPage(QWidget):
    commandRequested = Signal(str, object)
    refreshRequested = Signal()

    def __init__(self, panel):
        super().__init__(); self.setObjectName('Page')
        self.panel = panel
        self.state = None; self.online = False; self.busy = False
        self.pending = {}; self.sent = {}
        self.debounce = QTimer(self); self.debounce.setSingleShot(True); self.debounce.setInterval(120)
        self.debounce.timeout.connect(self.commit)
        layout = QVBoxLayout(self); layout.setContentsMargins(22, 18, 22, 16); layout.setSpacing(10)
        header = QHBoxLayout()
        titles = QVBoxLayout(); titles.setSpacing(2)
        self.title = panel.text('Smarteck', 'Title'); titles.addWidget(self.title)
        self.subtitle = panel.text('SLAMP1 · SmartThings', 'Small'); titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.power = IconButton('power', 'Ligar lâmpada', size=40)
        self.power.clicked.connect(lambda: self.request('power', not bool(self.state and self.state.power)))
        header.addWidget(self.power)
        close = IconButton('close', 'Fechar painel', size=30); close.clicked.connect(panel.dismiss); header.addWidget(close)
        layout.addLayout(header)
        self.scene = BulbScene(); layout.addWidget(self.scene)
        self.reading = panel.text('Conecte o SmartThings para começar', 'Muted')
        self.reading.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(self.reading)
        layout.addSpacing(4)
        self.level_section, self.level, self.level_value = self.slider_section('Brilho', 'Intensidade do brilho', 1, 100)
        layout.addWidget(self.level_section)
        self.white_section, self.kelvin, self.kelvin_value = self.slider_section('Temperatura do branco', 'Temperatura da luz branca em kelvin', 2000, 6500)
        self.kelvin.setSingleStep(100); self.kelvin.setPageStep(500)
        self.kelvin.setStyleSheet('QSlider::groove:horizontal { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ebb677,stop:1 #d6e9f4); } QSlider::sub-page:horizontal { background: transparent; }')
        self.white_presets = Segmented()
        self.white_presets.setAccessibleName('Presets de luz branca')
        self.white_presets.configure([(code, caption) for code, caption, _ in WHITE_PRESETS])
        self.white_presets.selected.connect(self.apply_white_preset)
        for button, (_, caption, _) in zip(self.white_presets.buttons, WHITE_PRESETS):
            button.setAccessibleName('Aplicar branco '+caption.lower())
        self.white_section.layout().insertWidget(1, self.white_presets)
        bounds = QHBoxLayout(); bounds.addWidget(panel.text('Quente', 'Small')); bounds.addStretch(); bounds.addWidget(panel.text('Frio', 'Small'))
        self.white_section.layout().addLayout(bounds); layout.addWidget(self.white_section)
        self.color_section, self.hue, self.hue_value = self.slider_section('Cor', 'Tonalidade da cor', 0, 360)
        self.hue.setPageStep(30)
        self.hue.setStyleSheet('QSlider::groove:horizontal { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #dd6372,stop:0.17 #d9cd63,stop:0.33 #61bd80,stop:0.5 #61b9c5,stop:0.67 #7988d3,stop:0.83 #bd78ca,stop:1 #dd6372); } QSlider::sub-page:horizontal { background: transparent; }')
        self.saturation_section, self.saturation, self.saturation_value = self.slider_section('Saturação', 'Saturação da cor', 0, 100)
        self.color_section.layout().addWidget(self.saturation_section); layout.addWidget(self.color_section)
        self.level.valueChanged.connect(lambda value: self.propose('level', value))
        self.kelvin.valueChanged.connect(lambda value: self.propose('kelvin', value))
        self.hue.valueChanged.connect(self.propose_color); self.saturation.valueChanged.connect(self.propose_color)
        for slider in self.sliders:
            slider.sliderReleased.connect(self.commit)
        self.connect_button = QPushButton('Conectar lâmpada'); self.connect_button.setObjectName('Primary')
        self.connect_button.clicked.connect(self.setup); layout.addWidget(self.connect_button)
        layout.addStretch(1); panel.separator(layout)
        footer = QHBoxLayout(); footer.setSpacing(8)
        self.status = panel.text('Conta ainda não conectada', 'Small'); self.status.setWordWrap(True)
        self.status.setAccessibleName('Estado da conexão da lâmpada'); footer.addWidget(self.status, 1)
        self.refresh = IconButton('refresh', 'Atualizar lâmpada', size=30); self.refresh.clicked.connect(self.refreshRequested.emit)
        footer.addWidget(self.refresh)
        setup = IconButton('settings', 'Configurar lâmpada e conta', size=30); setup.clicked.connect(self.setup)
        footer.addWidget(setup); layout.addLayout(footer)

    @property
    def sliders(self): return (self.level, self.kelvin, self.hue, self.saturation)

    def setup(self):
        self.panel.show_page(3 if getattr(self, 'provider', 'local') == 'smartthings' else 4)

    def slider_section(self, caption, accessible, minimum, maximum):
        section = QWidget(); layout = QVBoxLayout(section); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(3)
        row = QHBoxLayout(); row.addWidget(self.panel.text(caption, 'Section')); row.addStretch()
        reading = self.panel.text('—', 'Small'); row.addWidget(reading); layout.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(minimum, maximum); slider.setFixedHeight(26)
        slider.setAccessibleName(accessible); layout.addWidget(slider)
        return section, slider, reading

    def render(self, state, online, busy, message, info, configured, error=False, operation=None):
        self.state, self.online, self.busy = state, online, busy
        self.provider = info.get('provider', 'local')
        self.subtitle.setText('SLAMP1 · '+('Wi-Fi local' if self.provider == 'local' else 'SmartThings'))
        self.scene.reduced = self.panel.reduced
        self.white_presets.reduced = self.panel.reduced
        if not busy: self.sent.clear()
        self.title.setText(info.get('name') or 'Smarteck')
        self.power.active = bool(state and online and state.power); self.power.update()
        self.power.setEnabled(bool(online and not busy and state and state.power is not None))
        self.power.setAccessibleName('Desligar lâmpada' if state and state.power else 'Ligar lâmpada')
        self.power.setToolTip(self.power.accessibleName())
        self.scene.confirm(state if online else None)
        self.reading.setText(('Ligada' if state.power else 'Desligada') if online and state else ('Sem conexão · última leitura' if state else 'Conecte sua lâmpada para começar'))
        self.connect_button.setVisible(not configured or error)
        self.refresh.setEnabled(configured and not busy)
        available = bool(online and state and state.power and not busy)
        for section, capability in ((self.level_section, 'switchLevel'), (self.white_section, 'colorTemperature'), (self.color_section, 'colorControl')):
            section.setVisible(not state or capability in state.capabilities)
            section.setEnabled(available)
        if state:
            self.kelvin.setAccessibleName('Temperatura da luz branca, do quente ao frio' if state.white_unit == '%' else 'Temperatura da luz branca em kelvin')
            self.kelvin.setSingleStep(1 if state.white_unit == '%' else 100)
            self.kelvin.setPageStep(10 if state.white_unit == '%' else 500)
            self.sync_slider(self.level, state.minimum_level, state.maximum_level, state.level, 'level')
            self.sync_slider(self.kelvin, state.minimum_kelvin, state.maximum_kelvin, state.kelvin, 'kelvin')
            self.sync_slider(self.hue, 0, 360, state.hue*3.6 if state.hue is not None else None, 'color')
            self.sync_slider(self.saturation, 0, 100, state.saturation if state.saturation is not None else 100, 'color')
        selected = None
        for button, (code, caption, kelvin) in zip(self.white_presets.buttons, WHITE_PRESETS):
            value = white_preset_value(state, kelvin) if state else None
            button.setEnabled(available and value is not None)
            description = f'Branco {caption.lower()} · {kelvin} K'
            if state and state.white_unit == '%': description += f' aproximados · {value}% na escala local' if value is not None else ' indisponível'
            button.setToolTip(description)
            button.setAccessibleDescription(description)
            if online and state and state.color_mode in ('white', 'temperature', 'colorTemperature') and state.kelvin is not None and value is not None and abs(state.kelvin-value) <= (0.5 if state.white_unit == '%' else 50):
                selected = code
        self.white_presets.confirm(selected)
        self.update_values()
        self.status.setText(message)
        self.status.setStyleSheet(f'color: {(ERROR if error else SUBTLE).name()}; font-size: 11px;')

    def sync_slider(self, slider, minimum, maximum, value, kind):
        if kind in self.pending or kind in self.sent or slider.isSliderDown(): return
        slider.blockSignals(True); slider.setRange(minimum, maximum); slider.setValue(round(value) if value is not None else minimum); slider.blockSignals(False)

    def update_values(self):
        for kind, reading, slider, suffix in (('level', self.level_value, self.level, '%'), ('kelvin', self.kelvin_value, self.kelvin, ' K'), ('color', self.hue_value, self.hue, '°'), ('color', self.saturation_value, self.saturation, '%')):
            if kind == 'kelvin' and self.state and self.state.white_unit == '%': suffix = '%'
            attribute = {'level': 'level', 'kelvin': 'kelvin', self.hue: 'hue', self.saturation: 'saturation'}
            actual = getattr(self.state, attribute.get(slider, attribute.get(kind)), None) if self.state else None
            proposed = kind in self.pending or kind in self.sent
            display = slider.value() if proposed else (actual*3.6 if slider is self.hue and actual is not None else actual)
            reading.setText(f'{display:g}{suffix}' + (' · ajuste' if proposed else '') if display is not None else '—')
            slider.setAccessibleDescription(reading.text())

    def propose(self, kind, value):
        if not self.online or self.busy or not self.state or not self.state.power: return
        self.pending[kind] = value; self.update_values()
        self.status.setText('Solte para enviar o ajuste' if any(s.isSliderDown() for s in self.sliders) else 'Preparando o ajuste…')
        if not any(s.isSliderDown() for s in self.sliders): self.schedule()

    def propose_color(self, _):
        self.propose('color', {'hue': round(self.hue.value()/3.6, 2), 'saturation': self.saturation.value()})

    def apply_white_preset(self, code):
        if not self.online or self.busy or not self.state or not self.state.power or 'colorTemperature' not in self.state.capabilities: return
        preset = next((item for item in WHITE_PRESETS if item[0] == code), None)
        value = white_preset_value(self.state, preset[2]) if preset else None
        if value is None: return
        self.pending.pop('color', None)
        self.kelvin.blockSignals(True); self.kelvin.setValue(value); self.kelvin.blockSignals(False)
        self.pending['kelvin'] = value
        self.update_values(); self.commit()

    def schedule(self):
        if self.pending: self.debounce.start()

    def commit(self):
        self.debounce.stop()
        pending, self.pending = self.pending, {}
        if self.online and not self.busy:
            self.sent.update(pending)
            for kind, value in pending.items(): self.commandRequested.emit(kind, value)

    def request(self, kind, value):
        if self.online and not self.busy:
            self.commit(); self.commandRequested.emit(kind, value)

    def hideEvent(self, event):
        self.commit(); super().hideEvent(event)


class LampSetup(QWidget):
    authorizeRequested = Signal(str)
    searchRequested = Signal()
    connectRequested = Signal(dict)
    tokenPageRequested = Signal()
    disconnectRequested = Signal()

    def __init__(self, panel):
        super().__init__(); self.setObjectName('Page')
        layout = QVBoxLayout(self); layout.setContentsMargins(22, 16, 22, 16); layout.setSpacing(9)
        header = QHBoxLayout(); back = IconButton('back', 'Voltar à lâmpada', size=30)
        back.clicked.connect(lambda: panel.show_page(2)); header.addWidget(back)
        header.addWidget(panel.text('Conectar lâmpada', 'Title'), 1)
        close = IconButton('close', 'Fechar painel', size=30); close.clicked.connect(panel.dismiss); header.addWidget(close); layout.addLayout(header)
        intro = panel.text('Use a mesma conta Samsung em que sua SLAMP1 aparece no SmartThings. A conexão usa a internet e dispensa o IP.', 'Muted')
        intro.setWordWrap(True); layout.addWidget(intro)
        self.token_page = QPushButton('Abrir página de tokens Samsung')
        self.token_page.clicked.connect(self.tokenPageRequested.emit); layout.addWidget(self.token_page)
        scopes = panel.text('Crie um token com permissões para listar, ler e controlar dispositivos. Novos tokens pessoais duram 24 horas; gere outro quando expirar.', 'Small')
        scopes.setWordWrap(True); layout.addWidget(scopes)
        layout.addWidget(panel.text('Token SmartThings', 'Section'))
        self.token = QLineEdit(); self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText('Cole o token aqui'); self.token.setAccessibleName('Token de acesso SmartThings')
        layout.addWidget(self.token)
        self.authorize = QPushButton('Conectar conta e buscar lâmpadas'); self.authorize.setObjectName('Primary')
        self.authorize.clicked.connect(self.submit); self.token.returnPressed.connect(self.submit); layout.addWidget(self.authorize)
        self.credentials = panel.text('Token protegido pelo Windows neste usuário.', 'Small'); self.credentials.setWordWrap(True); layout.addWidget(self.credentials)
        panel.separator(layout)
        layout.addWidget(panel.text('Escolha a SLAMP1', 'Section'))
        self.found = Choice(); self.found.setAccessibleName('Lâmpadas encontradas no SmartThings'); self.found.addItem('Conecte a conta para buscar', None)
        layout.addWidget(self.found)
        self.connect = QPushButton('Usar lâmpada selecionada'); self.connect.clicked.connect(self.select); layout.addWidget(self.connect)
        self.search = QPushButton('Atualizar lista de lâmpadas'); self.search.clicked.connect(self.searchRequested.emit); layout.addWidget(self.search)
        self.status = panel.text('Conta ainda não conectada', 'Small'); self.status.setWordWrap(True); layout.addWidget(self.status)
        layout.addStretch(1)
        self.disconnect = QPushButton('Desconectar conta e apagar token'); self.disconnect.clicked.connect(self.disconnectRequested.emit); layout.addWidget(self.disconnect)

    def submit(self):
        if not self.token.text().strip():
            self.status.setText('Cole o token gerado na página da Samsung.'); self.token.setFocus(); return
        token = self.token.text().strip(); self.token.clear(); self.authorizeRequested.emit(token)

    def select(self):
        info = self.found.currentData()
        if info: self.connectRequested.emit(info)

    def set_found(self, devices, selected=None):
        self.found.clear()
        self.found.addItem('Selecione sua lâmpada' if devices else 'Nenhuma lâmpada nesta conta', None)
        for info in devices: self.found.addItem(info['name'], info)
        for index in range(1, self.found.count()):
            if self.found.itemData(index) == selected: self.found.setCurrentIndex(index); break

    def render(self, busy, message, configured, info, error=False, operation=None):
        self.status.setText(message); self.status.setStyleSheet(f'color: {(ERROR if error else SUBTLE).name()}; font-size: 11px;')
        self.authorize.setText('Conectando conta…' if busy and operation == 'authorize' else 'Conectar conta e buscar lâmpadas')
        for widget in (self.token, self.authorize, self.found): widget.setEnabled(not busy)
        self.connect.setEnabled(not busy and configured and self.found.count() > 1)
        self.search.setEnabled(not busy and configured); self.disconnect.setEnabled(not busy and configured)
        self.credentials.setText('Conta conectada · token protegido pelo Windows.' if configured else 'Token protegido pelo Windows neste usuário.')
