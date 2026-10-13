"""Tray lifecycle and serialized device operations; the popup owns presentation."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import logging
import time
from uuid import uuid4
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from . import autostart
from .icons import orbit_icon
from aircon.device import Device
from aircon.discovery import discover
from shared.network import validate_host
from shared.storage import DATA_DIR, load_config, save_config
from .panel import ControlPanel
from aircon.ui import label
from lamp.smartthings import TOKEN_PAGE
from lamp.controller import LampController

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class Events(QObject):
    done = Signal(str, object, object)
    state_changed = Signal(object)
    progress = Signal(str)


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
        self.message = 'Conectando…' if self.config.get('host') else 'Buscando ar-condicionado…'
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='aircon')
        self.events = Events(); self.events.done.connect(self.finished)
        self.events.state_changed.connect(self.observed_state)
        self.events.progress.connect(self.command_progress)
        self.device.on_change = self.events.state_changed.emit
        self.device.on_progress = self.events.progress.emit
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
        self.panel.lamp_local_setup.reconnectRequested.connect(self.lamp.retry_local)
        self.panel.lamp_local_setup.helpRequested.connect(lambda: QDesktopServices.openUrl(QUrl('https://github.com/jasonacox/tinytuya#setup-wizard---getting-local-keys')))
        self.panel.commandRequested.connect(self.command)
        self.panel.refreshRequested.connect(self.refresh)
        self.panel.searchRequested.connect(self.search)
        self.panel.connectRequested.connect(self.connect_to)
        self.panel.startupRequested.connect(self.toggle_startup)
        self.panel.motionRequested.connect(self.reduce_motion)
        self.panel.quitRequested.connect(self.app.quit)
        self.panel.logsRequested.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR/'orbit.log'))))
        self.tray = QSystemTrayIcon(orbit_icon(False), self)
        self.tray.activated.connect(self.activated)
        self.sync_panel(); self.tray.show()
        self.timer = QTimer(self); self.timer.setInterval(2500); self.timer.timeout.connect(self.poll); self.timer.start()
        self.app.aboutToQuit.connect(self.shutdown)
        self.executor.submit(self.repair_startup)
        QTimer.singleShot(300, self.start)

    def repair_startup(self):
        try: autostart.ensure_current()
        except Exception as error:
            LOG.warning('[startup] stage=registration_failed reason=%s', type(error).__name__)

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.Context):
            self.sync_panel(); self.panel.toggle_at(self.tray.geometry())

    def sync_panel(self):
        visible_busy = self.busy and (self.operation != 'refresh' or self.queued_command is not None)
        operation = 'command' if self.queued_command else self.operation
        self.panel.render(self.state, self.online, visible_busy, self.message, self.config,
                          autostart.enabled(), self.error, operation)
        self.sync_lamp()
        self.tray.setIcon(orbit_icon(self.online))
        if self.online and self.state:
            temp = f'{self.state.temperature:g} °{self.state.unit}' if self.state.temperature is not None else 'temperatura indisponível'
            self.tray.setToolTip(f'Orbit · {"Ligado" if self.state.power else "Desligado"} · {temp}\nClique para abrir os controles')
        else:
            self.tray.setToolTip('Orbit · ' + self.message)

    def sync_lamp(self):
        visible_busy = self.lamp.busy and (self.lamp.operation != 'refresh' or bool(self.lamp.queue))
        self.panel.render_lamp(self.lamp.state, self.lamp.online, visible_busy, self.lamp.message,
                               self.lamp.info, self.lamp.configured, self.lamp.error, self.lamp.operation,
                               bool(self.lamp.cloud.token))

    def observed_state(self, state):
        if self.online:
            self.state = self.device.snapshot()
            self.sync_panel()

    def command_progress(self, message):
        if self.operation == 'command':
            self.message = message
            self.sync_panel()

    def submit(self, operation, work):
        if self.busy: return
        self.busy = True; self.error = False; self.operation = operation
        self.message = {'connect': 'Conectando ao aparelho…', 'discover': 'Buscando na rede…',
                        'command': 'Enviando e conferindo…', 'refresh': 'Atualizando leitura…'}[operation]
        self.sync_panel()
        submitted = time.perf_counter()
        def run():
            started = time.perf_counter()
            LOG.info('[latency] operation=%s stage=worker_started queue_ms=%.1f', operation, (started-submitted)*1000)
            try:
                self.events.done.emit(operation, work(), None)
            except Exception as error:
                LOG.warning('%s: %s: %s', operation, type(error).__name__, error)
                self.events.done.emit(operation, None, error)
            finally:
                LOG.info('[latency] operation=%s stage=worker_finished total_ms=%.1f', operation, (time.perf_counter()-submitted)*1000)
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
            return connected, self.device.snapshot()
        self.submit('connect', work)

    def search(self):
        self.submit('discover', lambda: discover(self.config.get('device_id')))

    def poll(self):
        if self.busy or self.panel.pending_temperature is not None or self.panel.slider.isSliderDown(): return
        if self.online and not self.device.poll_needed(): return
        if self.online: self.submit('refresh', self.device.poll)
        elif self.config.get('host'): self.connect_to(self.config)
        else: self.search()

    def refresh(self):
        if self.online:
            self.submit('refresh', self.device.refresh)
        else:
            self.poll()

    def command(self, kind, value, requested_at=None, request_id=None):
        requested_at = requested_at if requested_at is not None else time.perf_counter()
        request_id = request_id or uuid4().hex[:8]
        LOG.info('[latency] id=%s kind=%s stage=ui_requested queued=%s', request_id, kind, self.busy)
        if self.busy:
            if self.operation == 'refresh':
                self.queued_command = (kind, value, requested_at, request_id); self.sync_panel()
            else:
                LOG.info('[latency] id=%s stage=discarded reason=busy', request_id)
            return
        self._command_requested_at = requested_at
        self._request_id = request_id
        command_id = self._request_id
        self.submit('command', lambda: self.device.command(kind, value, request_id=command_id))

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
                self.tray.showMessage('Orbit', str(error), QSystemTrayIcon.MessageIcon.Warning, 6000)
            if operation == 'command' and self.device.resources:
                from aircon.device import state_from_resources
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
            else: self.state = self.device.snapshot()
            self.online = True; self.message = 'Estado confirmado pelo aparelho'
        if queued and not error and self.online:
            self.command(*queued); return
        self.sync_panel()
        if operation == 'command' and hasattr(self, '_command_requested_at'):
            LOG.info('[latency] id=%s stage=ui_applied total_ms=%.1f success=%s',
                     self._request_id, (time.perf_counter()-self._command_requested_at)*1000, error is None)
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
