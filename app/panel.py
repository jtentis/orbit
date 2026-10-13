from __future__ import annotations
from PySide6.QtCore import (
    Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer, QRectF, QRect, QPoint,
)
from PySide6.QtGui import QPainter, QPen, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSlider, QLineEdit, QScrollArea, QFrame, QLayout,
)

from shared.ui import (
    BG, SURFACE, SUBTLE, ACCENT, BORDER, ERROR, windows_motion_enabled,
    IconButton, Toggle, Segmented, Choice, PageStack, STYLE,
)
from shared.network import validate_host
from windfree.ui import LABELS, label, TemperatureReadout, AirConditioner
from lamp.ui import LampPage, LampSetup
from lamp.local_setup import LocalLampSetup


def popup_position(anchor: QRect, available: QRect, width: int, height: int):
    return QPoint(max(available.left(), available.right()+1-width),
                  max(available.top(), available.bottom()+1-height))


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
        self.debounce = QTimer(self); self.debounce.setSingleShot(True); self.debounce.setInterval(120)
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
        self.slider.sliderReleased.connect(self.commit_temperature)
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
        logs = QPushButton('Abrir logs e tempos'); logs.clicked.connect(self.logsRequested.emit); layout.addWidget(logs)
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
            footer = message
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
        self.modes.configure([(code, short.get(code, label(code))) for code in state.modes], LABELS); self.modes.confirm(state.mode)
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
        self.debounce.stop()
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
        if index == 4: self.lamp_local_setup.opened()
        self.fit_visible_page()
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
        elif index == 4: self.lamp_local_setup.focus_default()
        elif index == 2:
            (self.lamp_page.power if self.lamp_page.power.isEnabled() else self.lamp_page.connect_button).setFocus()
        else: self.power_button.setFocus()

    def select_device(self, code):
        self.active_device = code; self.devices.confirm(code)
        self.show_page(2 if code == 'lamp' else 0)

    def render_lamp(self, state, online, busy, message, info, configured, error=False, operation=None, cloud_configured=None):
        self.lamp_page.render(state, online, busy, message, info, configured, error, operation)
        self.lamp_setup.render(busy, message, configured if cloud_configured is None else cloud_configured, info, error, operation)
        self.lamp_local_setup.render(busy, message, info, error, operation, configured=configured, online=online)

    def fit_visible_page(self):
        if not self.isVisible(): return
        available = self.screen().availableGeometry()
        desired = 340 if self.pages.currentIndex() == 4 and self.lamp_local_setup.compact else 650
        height = min(desired, available.height()-24)
        if self.height() == height: return
        self.position_animation.stop(); self.setFixedHeight(height)
        self._target_position = popup_position(QRect(), available, self.width(), self.height())
        self.move(self._target_position)

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
