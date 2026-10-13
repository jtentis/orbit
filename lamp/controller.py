"""Independent lighting worker: cloud failures never block local AC controls."""
from concurrent.futures import ThreadPoolExecutor
import logging
import time
from uuid import uuid4
from PySide6.QtCore import QObject, Signal, QTimer
from .smartthings import SmartThingsLamp, AuthorizationError
from .local import LocalLamp, discover_local
from shared.storage import load_secret, save_secret, save_config, DATA_DIR

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class LampEvents(QObject):
    done = Signal(str, object, object)
    progress = Signal(str)


class LampController(QObject):
    changed = Signal()
    found = Signal(object)
    found_local = Signal(object)
    connected = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.cloud = SmartThingsLamp(); self.local = LocalLamp(); self.device = self.cloud
        self.state = None; self.online = False; self.busy = False; self.error = False
        self.operation = None; self.configured = False; self.auth_failed = False
        self.message = 'Lâmpada ainda não configurada'
        self.queue = {}
        self.request_times = {}
        self.active_request = None
        self.local_failures = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='lamp')
        self.events = LampEvents(); self.events.done.connect(self.finished)
        self.events.progress.connect(self.command_progress)
        self.local.on_progress = self.events.progress.emit
        self.timer = QTimer(self); self.timer.setInterval(30000); self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.start_timer = QTimer(self); self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self.start); self.start_timer.start(400)

    @property
    def info(self): return self.config.get('lamp', {})

    def command_progress(self, message):
        if self.busy and self.operation == 'command':
            self.message = message; self.changed.emit()

    def submit(self, operation, work):
        if self.busy: return
        submitted = time.perf_counter()
        self.busy = True; self.error = False; self.operation = operation
        self.message = {'authorize': 'Conectando conta e buscando lâmpadas…', 'discover': 'Buscando lâmpadas no SmartThings…',
                        'discover_local': 'Buscando dispositivos Tuya na rede…',
                        'connect': 'Lendo a lâmpada selecionada…', 'refresh': 'Atualizando leitura…',
                        'command': 'Enviando e conferindo…', 'disconnect': 'Removendo conexão…', 'disconnect_cloud': 'Desconectando conta…'}[operation]
        self.changed.emit()
        def run():
            LOG.info('[latency] operation=%s stage=worker_started queue_ms=%.1f', operation, (time.perf_counter()-submitted)*1000)
            try: self.events.done.emit(operation, work(), None)
            except Exception as error:
                LOG.warning('Iluminação %s: %s', operation, type(error).__name__)
                self.events.done.emit(operation, None, error)
            finally:
                LOG.info('[latency] operation=%s stage=worker_finished total_ms=%.1f', operation, (time.perf_counter()-submitted)*1000)
        self.executor.submit(run)

    def start(self):
        if self.info.get('provider') == 'local':
            try:
                secret = load_secret('local-lamp')
                if not secret or secret.get('device_id') != self.info.get('device_id'):
                    raise ValueError()
            except Exception:
                self.error = True; self.message = 'Conecte novamente a lâmpada com sua chave local.'; self.changed.emit(); return
            self.connect_local(self.info, secret['key']); return
        try: secret = load_secret('smartthings-lamp')
        except Exception:
            self.error = True; self.message = 'Não foi possível ler o token protegido. Conecte a conta novamente.'
            self.changed.emit(); return
        if not secret or not secret.get('token'):
            self.search_local(); return
        try: self.cloud.authorize(secret['token'])
        except ValueError:
            self.error = True; self.message = 'Token salvo inválido. Conecte a conta novamente.'
            self.changed.emit(); return
        self.configured = True
        if self.info.get('device_id'): self.connect_to(self.info)
        else: self.search()

    def authorize(self, token):
        if self.busy: return
        def work():
            previous = self.cloud.token
            try:
                self.cloud.authorize(token)
                devices = self.cloud.discover()
                save_secret('smartthings-lamp', {'token': self.cloud.token})
                return devices
            except Exception:
                self.cloud.token = previous
                raise
        self.submit('authorize', work)

    def search(self):
        if self.cloud.token and not self.busy: self.submit('discover', self.cloud.discover)

    def search_local(self):
        self.submit('discover_local', discover_local)

    def connect_local(self, info, key):
        if self.busy: return
        def work():
            state = self.local.connect(info, key)
            save_secret('local-lamp', {'key': key, 'device_id': info['device_id']})
            name = info.get('name') if not str(info.get('name', '')).startswith('Dispositivo Tuya') else None
            connected = {**info, 'provider': 'local', 'name': name or 'Smarteck SLAMP1'}
            return connected, state
        self.submit('connect', work)

    def connect_to(self, info):
        if not self.cloud.token or self.busy: return
        def work(): return {**info, 'provider': 'smartthings'}, self.cloud.connect(info)
        self.submit('connect', work)

    def poll(self):
        if self.busy or not self.configured or self.auth_failed: return
        panel = getattr(self.parent(), 'panel', None)
        if panel and (panel.lamp_page.pending or any(s.isSliderDown() for s in panel.lamp_page.sliders)): return
        if isinstance(self.device, LocalLamp):
            self.submit('refresh', self.device.refresh)
        elif self.device.device_id: self.submit('refresh', self.device.refresh)
        elif self.info.get('device_id'): self.connect_to(self.info)

    def reconnect_local(self):
        info, key = dict(self.info), self.local.key
        def work():
            found = discover_local(info.get('device_id'))
            if not found: raise RuntimeError('Lâmpada não encontrada na rede. Confira sua alimentação e Wi-Fi.')
            connected = {**found[0], 'name': info.get('name', 'Smarteck SLAMP1')}
            return connected, self.local.connect(connected, key)
        self.submit('connect', work)

    def command(self, kind, value, requested_at=None, request_id=None):
        requested_at = requested_at or time.perf_counter(); request_id = request_id or uuid4().hex[:8]
        LOG.info('[latency] id=%s kind=%s stage=ui_requested queued=%s', request_id, kind, self.busy)
        if self.busy:
            if self.operation in ('refresh', 'command'):
                self.queue[kind] = value
                self.request_times[kind] = (requested_at, request_id)
                self.changed.emit()
            return
        if self.online:
            self.active_request = (requested_at, request_id)
            if isinstance(self.device, LocalLamp):
                self.submit('command', lambda: self.device.command(kind, value, request_id=request_id))
            else: self.submit('command', lambda: self.device.command(kind, value))

    def disconnect(self):
        if self.busy: return
        def work():
            secret_name = 'local-lamp' if isinstance(self.device, LocalLamp) else 'smartthings-lamp'
            (DATA_DIR / (secret_name+'.dpapi')).unlink(missing_ok=True)
            self.device.close()
        self.submit('disconnect', work)

    def disconnect_cloud(self):
        if not isinstance(self.device, LocalLamp): self.disconnect(); return
        if self.busy: return
        def work():
            (DATA_DIR / 'smartthings-lamp.dpapi').unlink(missing_ok=True)
            self.cloud.close()
        self.submit('disconnect_cloud', work)

    def finished(self, operation, result, error):
        self.busy = False; self.error = error is not None
        if error:
            cloud_setup = operation in ('authorize', 'discover') and isinstance(self.device, LocalLamp)
            if isinstance(error, AuthorizationError) and not cloud_setup: self.auth_failed = True
            if not isinstance(error, ValueError) and not cloud_setup: self.online = False
            self.message = str(error) if type(error) in (RuntimeError, ValueError, AuthorizationError) else 'Falha ao acessar a lâmpada. Tente conectar novamente.'
            if operation == 'command' and self.device.state: self.state = self.device.state
            self.queue.clear()
            self.request_times.clear()
            if operation == 'refresh' and isinstance(self.device, LocalLamp):
                self.local_failures += 1
                if self.local_failures >= 3:
                    self.local_failures = 0; self.reconnect_local(); return
        elif operation == 'disconnect_cloud':
            self.cloud = SmartThingsLamp(); self.message = 'Conta Samsung desconectada; controle local disponível.'
            self.found.emit([])
        elif operation == 'discover_local':
            self.found_local.emit(result)
            self.message = 'Dispositivo encontrado. Informe a chave local para verificar a lâmpada.' if result else 'Nenhum Tuya encontrado. Confira se a lâmpada está energizada e na mesma rede.'
        elif operation in ('authorize', 'discover'):
            self.auth_failed = False
            if self.info.get('provider') != 'local': self.configured = True
            self.found.emit(result)
            self.message = 'Selecione sua SLAMP1 e clique em Usar lâmpada selecionada.' if result else 'Nenhuma lâmpada encontrada. Confira a conta Samsung e as permissões.'
            selected = next((item for item in result if item['device_id'] == self.info.get('device_id') and item['component'] == self.info.get('component')), None)
            if self.info.get('provider') != 'local' and selected:
                self.connect_to(selected); return
        elif operation == 'disconnect':
            self.config.pop('lamp', None); save_config(self.config)
            if isinstance(self.device, LocalLamp):
                self.local = LocalLamp(); self.local.on_progress = self.events.progress.emit
            else: self.cloud = SmartThingsLamp()
            self.device = self.cloud; self.state = None
            self.online = self.configured = self.auth_failed = False
            self.message = 'Conexão removida · credencial apagada'; self.found.emit([]); self.found_local.emit([])
        else:
            if operation == 'connect':
                info, self.state = result; self.config['lamp'] = info; save_config(self.config)
                self.device = self.local if info.get('provider') == 'local' else self.cloud
                self.configured = True
                LOG.info('Conexão da lâmpada estabelecida; transporte=%s; energia=%s; brilho=%s',
                          info.get('provider'), self.state.power, self.state.level)
            else: self.state = result
            self.online = True; self.auth_failed = False
            self.local_failures = 0
            self.message = ('Wi-Fi local · confirmado pela lâmpada' if isinstance(self.device, LocalLamp) else
                'SmartThings · estado confirmado' if self.state.health == 'ONLINE' else 'SmartThings · leitura recebida, conexão do dispositivo não informada')
            if operation == 'connect': self.connected.emit()
        if self.queue and not error and self.online:
            self.changed.emit()
            self.log_applied(operation, error)
            kind = next(iter(self.queue)); value = self.queue.pop(kind)
            timing = self.request_times.pop(kind, (None, None))
            self.command(kind, value, *timing); return
        self.changed.emit()
        self.log_applied(operation, error)

    def log_applied(self, operation, error):
        if operation == 'command' and self.active_request:
            started, request_id = self.active_request
            LOG.info('[latency] id=%s stage=ui_applied total_ms=%.1f success=%s',
                     request_id, (time.perf_counter()-started)*1000, error is None)
            self.active_request = None

    def shutdown(self):
        self.start_timer.stop(); self.timer.stop(); self.queue.clear(); self.request_times.clear()
        self.executor.submit(self.cloud.close); self.executor.submit(self.local.close)
        self.executor.shutdown(wait=False, cancel_futures=False)
