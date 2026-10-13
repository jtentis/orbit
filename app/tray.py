"""Tray lifecycle and serialized device operations; the popup owns presentation."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import logging
from PySide6.QtCore import QObject, Signal, QTimer, Qt, QUrl
from PySide6.QtGui import QIcon, QPainter, QColor, QPixmap, QPen, QDesktopServices
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from . import autostart
from windfree.device import Device
from windfree.discovery import discover
from shared.network import validate_host
from shared.storage import DATA_DIR, load_config, save_config
from .panel import ControlPanel
from windfree.ui import label
from lamp.smartthings import TOKEN_PAGE
from lamp.controller import LampController

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def tray_icon(state=None, online=False):
    pixmap = QPixmap(64, 64); pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor('#36b9e8') if online and state and state.power else QColor('#98a5b3')
    painter.setPen(QPen(color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for angle in (0, 60, 120):
        painter.save(); painter.translate(32, 32); painter.rotate(angle)
        painter.drawLine(0, -24, 0, 24)
        for direction in (-1, 1):
            y = direction*16
            painter.drawLine(0, y, -7, y-direction*7); painter.drawLine(0, y, 7, y-direction*7)
        painter.restore()
    if not online:
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#d56c30'))
        painter.drawEllipse(46, 46, 14, 14)
    painter.end(); return QIcon(pixmap)


class Events(QObject):
    done = Signal(str, object, object)


class TrayApp(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = load_config()
        self.device = Device()
        self.state = None
        self.online = False
        self.busy = False
        self.error = False
        self.operation = None
        self.queued_command = None
        self.connection_failures = 0
        self.show_lamp_setup = '--show-lamp-setup' in app.arguments()
        show_lamp = '--show-lamp' in app.arguments() or self.show_lamp_setup
        self.show_after_connect = '--show-panel' in app.arguments() or show_lamp
        self.message = 'Conectando…' if self.config.get('host') else 'Buscando seu WindFree…'
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='windfree')
        self.events = Events(); self.events.done.connect(self.finished)
        self.panel = ControlPanel()
        if show_lamp: self.panel.select_device('lamp')
        self.lamp = LampController(self.config, self)
        self.lamp.changed.connect(self.sync_lamp)
        self.lamp.found.connect(lambda devices: self.panel.lamp_setup.set_found(devices, self.lamp.info))
        self.lamp.found_local.connect(lambda devices: self.panel.lamp_local_setup.set_found(devices, self.lamp.info))
        self.lamp.connected.connect(lambda: self.panel.show_page(2) if self.panel.active_device == 'lamp' else None)
        self.panel.lamp_page.commandRequested.connect(self.lamp.command)
        self.panel.lamp_page.refreshRequested.connect(self.lamp.poll)
        self.panel.lamp_setup.authorizeRequested.connect(self.lamp.authorize)
        self.panel.lamp_setup.searchRequested.connect(self.lamp.search)
        self.panel.lamp_setup.connectRequested.connect(self.lamp.connect_to)
        self.panel.lamp_setup.disconnectRequested.connect(self.lamp.disconnect_cloud)
        self.panel.lamp_setup.tokenPageRequested.connect(lambda: QDesktopServices.openUrl(QUrl(TOKEN_PAGE)))
        self.panel.lamp_local_setup.searchRequested.connect(self.lamp.search_local)
        self.panel.lamp_local_setup.connectRequested.connect(self.lamp.connect_local)
        self.panel.lamp_local_setup.disconnectRequested.connect(self.lamp.disconnect)
        self.panel.lamp_local_setup.helpRequested.connect(lambda: QDesktopServices.openUrl(QUrl('https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys')))
        self.panel.commandRequested.connect(self.command)
        self.panel.refreshRequested.connect(self.poll)
        self.panel.searchRequested.connect(self.search)
        self.panel.connectRequested.connect(self.connect_to)
        self.panel.startupRequested.connect(self.toggle_startup)
        self.panel.motionRequested.connect(self.reduce_motion)
        self.panel.quitRequested.connect(self.app.quit)
        self.panel.logsRequested.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR/'windfree.log'))))
        self.tray = QSystemTrayIcon(tray_icon(), self)
        self.tray.activated.connect(self.activated)
        self.sync_panel(); self.tray.show()
        self.timer = QTimer(self); self.timer.setInterval(20000); self.timer.timeout.connect(self.poll); self.timer.start()
        self.app.aboutToQuit.connect(self.shutdown)
        QTimer.singleShot(300, self.start)

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.Context):
            self.sync_panel(); self.panel.toggle_at(self.tray.geometry())

    def sync_panel(self):
        visible_busy = self.busy and (self.operation != 'refresh' or self.queued_command is not None)
        operation = 'command' if self.queued_command else self.operation
        self.panel.render(self.state, self.online, visible_busy, self.message, self.config,
                          autostart.enabled(), self.error, operation)
        self.sync_lamp()
        self.tray.setIcon(tray_icon(self.state, self.online))
        if self.online and self.state:
            temp = f'{self.state.temperature:g} °{self.state.unit}' if self.state.temperature is not None else 'temperatura indisponível'
            self.tray.setToolTip(f'WindFree · {"Ligado" if self.state.power else "Desligado"} · {temp}\nClique para abrir os controles')
        else:
            self.tray.setToolTip('WindFree · ' + self.message)

    def sync_lamp(self):
        visible_busy = self.lamp.busy and (self.lamp.operation != 'refresh' or bool(self.lamp.queue))
        self.panel.render_lamp(self.lamp.state, self.lamp.online, visible_busy, self.lamp.message,
                               self.lamp.info, self.lamp.configured, self.lamp.error, self.lamp.operation,
                               bool(self.lamp.cloud.token))

    def submit(self, operation, work):
        if self.busy: return
        self.busy = True; self.error = False; self.operation = operation
        self.message = {'connect': 'Conectando ao aparelho…', 'discover': 'Buscando na rede…',
                        'command': 'Enviando e conferindo…', 'refresh': 'Atualizando leitura…'}[operation]
        self.sync_panel()
        def run():
            try:
                self.events.done.emit(operation, work(), None)
            except Exception as error:
                LOG.warning('%s: %s: %s', operation, type(error).__name__, error)
                self.events.done.emit(operation, None, error)
        self.executor.submit(run)

    def start(self):
        if self.config.get('host'): self.connect_to(self.config)
        else: self.search()

    def connect_to(self, info):
        try:
            host = validate_host(info.get('host', ''))
        except ValueError as error:
            self.message = str(error); self.error = True; self.sync_panel(); return
        def work():
            connected = self.device.connect(host, info.get('device_id'), info.get('port'))
            return connected, self.device.refresh()
        self.submit('connect', work)

    def search(self):
        self.submit('discover', lambda: discover(self.config.get('device_id')))

    def poll(self):
        if self.busy or self.panel.pending_temperature is not None or self.panel.slider.isSliderDown(): return
        if self.online: self.submit('refresh', self.device.refresh)
        elif self.config.get('host'): self.connect_to(self.config)
        else: self.search()

    def command(self, kind, value):
        if self.busy:
            if self.operation == 'refresh':
                self.queued_command = (kind, value); self.sync_panel()
            return
        self.submit('command', lambda: self.device.command(kind, value))

    def finished(self, operation, result, error):
        self.busy = False; self.error = error is not None
        queued = self.queued_command; self.queued_command = None
        if error:
            if operation in ('connect', 'refresh') or not isinstance(error, ValueError): self.online = False
            self.message = str(error)
            if operation == 'connect':
                self.connection_failures += 1
                if self.connection_failures >= 3 and self.config.get('device_id'):
                    self.connection_failures = 0; self.search(); return
            if operation != 'refresh' and not self.panel.isVisible():
                self.tray.showMessage('WindFree', str(error), QSystemTrayIcon.MessageIcon.Warning, 6000)
            if operation == 'command' and self.device.resources:
                from windfree.device import state_from_resources
                self.state = state_from_resources(self.device.resources)
        elif operation == 'discover':
            self.panel.set_found(result)
            if len(result) == 1:
                self.config.update(result[0]); save_config(self.config); self.connect_to(result[0]); return
            self.message = 'Escolha um aparelho encontrado.' if result else 'Aparelho não encontrado. Confira a rede ou informe o IP.'
        else:
            if operation == 'connect':
                info, self.state = result; self.config.update(info); save_config(self.config)
                self.connection_failures = 0
                LOG.info('Conexão local estabelecida; energia=%s; temperatura=%s', self.state.power, self.state.temperature)
            else: self.state = result
            self.online = True; self.message = 'Estado confirmado pelo aparelho'
        if queued and not error and self.online:
            self.command(*queued); return
        self.sync_panel()
        if self.show_after_connect and self.online:
            self.show_after_connect = False
            if not self.panel.isVisible():
                self.panel.toggle_at(self.tray.geometry())
                if self.show_lamp_setup:
                    self.show_lamp_setup = False; self.panel.show_page(4)

    def toggle_startup(self, value):
        try:
            autostart.set_enabled(value)
        except OSError as error:
            self.error = True; self.message = str(error)
        self.sync_panel()

    def reduce_motion(self, value):
        self.config['reduce_motion'] = value; save_config(self.config); self.sync_panel()

    def shutdown(self):
        self.timer.stop(); self.tray.hide(); self.panel.hide()
        self.lamp.shutdown()
        self.executor.submit(self.device.close)
        self.executor.shutdown(wait=False, cancel_futures=False)
