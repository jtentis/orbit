"""Capability-driven control; no commands are inferred from a model name."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import copy
import logging
import threading
from uuid import uuid4
import time
import cbor2
from smartthings_local.protocol.dtls_session import DtlsCoapSession
from smartthings_local.protocol.dtls_probe import probe_dtls_ports
from .discovery import inspect_host, validate_host
from .identity import client_identity

V = 'x.com.samsung.da.'
MODE = '/mode/vs/0'
PRESET = '/mode/convenient/vs/0'
FAN = '/wind/strength/vs/0'
SWING = '/wind/direction/vs/0'

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


class ResourceUnavailable(ConnectionError):
    pass


def flatten_resources(value) -> dict[str, dict]:
    found = {}
    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get('href'), str) and isinstance(node.get('rep'), dict):
                found[node['href']] = node['rep']
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    return found


def first(value):
    return value[0] if isinstance(value, list) and value else value


def numeric(value, default=None):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (ValueError, TypeError):
        return default


@dataclass
class State:
    power: bool | None = None
    temperature: float | None = None
    current: float | None = None
    minimum: float = 16
    maximum: float = 30
    step: float = 1
    unit: str = 'C'
    mode: str | None = None
    fan: str | None = None
    swing: str | None = None
    preset: str | None = None
    modes: list[str] = field(default_factory=list)
    fans: list[tuple[str, str]] = field(default_factory=list)
    swings: list[str] = field(default_factory=list)
    presets: list[str] = field(default_factory=list)
    temperature_writable: bool = False
    power_writable: bool = False
    windfree: bool | None = None
    display_light: bool | None = None


def state_from_resources(resources: dict) -> State:
    state = State()
    power = resources.get('/power/vs/0', {}).get(V + 'power')
    state.power = (power == 'On') if power in ('On', 'Off') else resources.get('/power/0', {}).get('value')
    state.power_writable = '/power/vs/0' in resources or '/power/0' in resources
    vendor_items = resources.get('/temperatures/vs/0', {}).get(V + 'items', [])
    item = vendor_items[0] if vendor_items else {}
    desired = resources.get('/temperature/desired/0', {})
    current = resources.get('/temperature/current/0', {})
    state.temperature = numeric(desired.get('temperature'), numeric(item.get(V + 'desired')))
    state.current = numeric(current.get('temperature'), numeric(item.get(V + 'current')))
    bounds = desired.get('range', [item.get(V + 'minimum', 16), item.get(V + 'maximum', 30)])
    if isinstance(bounds, list) and len(bounds) == 2:
        state.minimum = numeric(bounds[0], 16)
        state.maximum = numeric(bounds[1], 30)
    state.step = numeric(resources.get('/temperature/control/vs/0', {}).get(V + 'increment'),
                         numeric(item.get(V + 'increment'), 1))
    if state.step <= 0:
        state.step = 1
    state.unit = str(desired.get('units', item.get(V + 'unit', 'C')))
    state.unit = 'F' if state.unit in ('F', 'Fahrenheit') else 'C'
    state.temperature_writable = bool(desired or item)
    mode = resources.get(MODE, {})
    state.mode = first(mode.get(V + 'modes'))
    state.modes = list(mode.get(V + 'supportedModes', []))
    # Samsung Light encodes the display-off flag.
    light_option = next((o for o in mode.get(V + 'options', []) if o in ('Light_On', 'Light_Off')), None)
    if light_option is not None:
        state.display_light = light_option == 'Light_Off'
    else:
        light_mode = resources.get('/light/vs/0', {}).get('mode')
        if light_mode in ('On', 'Off'):
            state.display_light = light_mode == 'On'
    fan = resources.get(FAN, {})
    state.fan = first(fan.get(V + 'modes'))
    codes = fan.get(V + 'supportedModes', [])
    names = fan.get(V + 'modesName', [])
    state.fans = [(code, names[i] if i < len(names) else code) for i, code in enumerate(codes)]
    swing = resources.get(SWING, {})
    state.swing = first(swing.get(V + 'modes'))
    state.swings = list(swing.get(V + 'supportedModes', []))
    preset = resources.get(PRESET, {})
    state.preset = first(preset.get(V + 'modes'))
    state.presets = list(preset.get(V + 'supportedModes', []))
    if 'Nano' in state.presets:
        state.windfree = state.preset in ('Nano', 'NanoSleep')
    dedicated = resources.get('/modeoption/windfree/vs/0', {})
    if V + 'windfree' in dedicated:
        state.windfree = dedicated[V + 'windfree'] in ('On', True)
    return state


def command_payload(kind: str, value, resources: dict) -> tuple[str, dict]:
    state = state_from_resources(resources)
    if kind == 'display_light' and state.display_light is not None:
        if not isinstance(value, bool):
            raise ValueError('Estado da luz inválido.')
        if any(o in ('Light_On', 'Light_Off') for o in resources.get(MODE, {}).get(V + 'options', [])):
            return MODE, {V + 'options': ['Light_Off' if value else 'Light_On']}
        return '/light/vs/0', {'mode': 'On' if value else 'Off'}
    if kind == 'power' and state.power_writable:
        if not isinstance(value, bool):
            raise ValueError('Estado de energia inválido.')
        if '/power/vs/0' in resources:
            return '/power/vs/0', {V + 'power': 'On' if value else 'Off'}
        return '/power/0', {'value': value}
    if kind == 'temperature' and state.temperature_writable:
        n = numeric(value)
        if n is None or not state.minimum <= n <= state.maximum:
            raise ValueError(f'Temperatura permitida: {state.minimum:g} a {state.maximum:g} °{state.unit}.')
        n = round(state.minimum + round((n - state.minimum) / state.step) * state.step, 2)
        n = max(state.minimum, min(state.maximum, n))
        if '/temperature/desired/0' in resources and '/temperature/current/0' in resources:
            return '/temperature/desired/0', {'temperature': n}
        items = resources['/temperatures/vs/0'][V + 'items']
        return '/temperatures/vs/0', {V + 'items': [{V + 'id': items[0].get(V + 'id', '0'), V + 'desired': str(n)}]}
    allowed = {'mode': (MODE, state.modes), 'fan': (FAN, [code for code, _ in state.fans]),
               'swing': (SWING, state.swings), 'preset': (PRESET, state.presets)}
    if kind in allowed:
        path, values = allowed[kind]
        if value not in values:
            raise ValueError('Esse controle não é suportado pelo aparelho.')
        return path, {V + 'modes': [value] if kind == 'mode' else value}
    if kind == 'windfree' and state.windfree is not None:
        if not isinstance(value, bool):
            raise ValueError('Estado WindFree inválido.')
        if '/modeoption/windfree/vs/0' in resources:
            return '/modeoption/windfree/vs/0', {V + 'windfree': 'On' if value else 'Off'}
        preset = 'NanoSleep' if value and state.preset in ('Sleep', 'NanoSleep') else ('Nano' if value else 'Off')
        if preset not in state.presets:
            raise ValueError('WindFree indisponível neste estado.')
        return PRESET, {V + 'modes': preset}
    raise ValueError('Controle indisponível neste aparelho.')


class Device:
    def __init__(self, on_change=None, on_progress=None, request_rate=20):
        self.session = None
        self.info = {}
        self.resources = {}
        self.on_change = on_change
        self.on_progress = on_progress
        self.request_rate = request_rate
        self.last_timing = {}
        self._condition = threading.Condition(threading.RLock())
        self._versions = {}
        self._reported_fields = {}
        self._observed = set()
        self._unsupported_reads = set()
        self._poll_index = 0
        self._generation = 0
        self._last_contact = 0

    def snapshot(self):
        with self._condition:
            return state_from_resources(copy.deepcopy(self.resources))

    def close(self):
        self._generation += 1
        session, self.session = self.session, None
        with self._condition:
            self._observed.clear()
            self._condition.notify_all()
        if session:
            session.close()

    def connect(self, host: str, expected_id: str | None = None, port: int | None = None) -> dict:
        started = time.perf_counter()
        validate_host(host)
        info = {'host': host, 'port': int(port), 'device_id': expected_id} if port else inspect_host(host, timeout=3)
        if not info:
            probe = probe_dtls_ports(host, (49154, 49153, 49155, 49152), timeout=2, retries=1)
            if probe.selected_port:
                info = {'host': host, 'port': probe.selected_port, 'device_id': expected_id}
        if not info:
            raise ConnectionError('O IP não respondeu como um ar-condicionado Samsung. Use Buscar aparelho.')
        if expected_id and info['device_id'] != expected_id:
            raise ConnectionError('O IP agora pertence a outro aparelho. Use Buscar aparelho para reencontrar o seu.')
        identity = client_identity()
        self.close()
        generation = self._generation
        session = DtlsCoapSession(host, info['port'], cert_pem=identity['cert'], key_pem=identity['key'],
                                  rate_limit_rps=self.request_rate,
                                  on_notification=lambda href, body: self._notification(generation, href, body))
        try:
            session.connect()
            session.start_reader()
            self.session = session
            peer = self.read('/oic/d')
            if 'oic.d.airconditioner' not in peer.get('rt', []):
                raise ConnectionError('Esse dispositivo não é um ar-condicionado.')
            if expected_id and peer.get('di') != expected_id:
                raise ConnectionError('Esse endereço pertence a outro aparelho. Use Buscar aparelho.')
            info.update(device_id=peer.get('di'), name=peer.get('n', 'Samsung WindFree'))
            self.info = info
            self._versions.clear(); self._unsupported_reads.clear()
            self._reported_fields.clear()
            self.resources = {}
            self.refresh()
            for href in self._status_paths():
                try:
                    session.subscribe(href.strip('/').split('/'))
                except Exception as error:
                    LOG.warning('observe path=%s error=%s', href, type(error).__name__)
            LOG.info('[latency] stage=connected total_ms=%.1f request_rate=%s',
                     (time.perf_counter()-started)*1000, self.request_rate)
        except Exception:
            self.close()
            raise
        return info

    def read(self, path: str, timeout=8):
        if not self.session:
            raise ConnectionError('Sem conexão com o ar-condicionado.')
        started = time.perf_counter()
        try:
            code, body = self.session.get(path.strip('/').split('/'), timeout=timeout)
            if code >> 5 != 2:
                error = ResourceUnavailable if code in (132, 133) else ConnectionError
                raise error(f'O aparelho recusou a leitura (CoAP {code >> 5}.{code & 31:02d}).')
            self._last_contact = time.monotonic()
            return cbor2.loads(body) if body else {}
        finally:
            LOG.info('[latency] stage=read path=%s duration_ms=%.1f', path, (time.perf_counter()-started)*1000)

    def refresh(self) -> State:
        with self._condition:
            versions = dict(self._versions)
        resources = flatten_resources(self.read('/device/0'))
        if not resources or MODE not in resources:
            raise ConnectionError('O aparelho não informou os controles de climatização.')
        with self._condition:
            updated = {}
            for href, rep in resources.items():
                if self._versions.get(href, 0) == versions.get(href, 0):
                    updated[href] = rep
                    self._reported_fields[href] = set(rep)
            for href, rep in self.resources.items():
                if self._versions.get(href, 0) != versions.get(href, 0):
                    updated[href] = rep
            self.resources = updated
            return self.snapshot()

    def _representation(self, href, data):
        if not isinstance(data, dict):
            raise ConnectionError('O aparelho retornou um recurso inválido.')
        return flatten_resources(data).get(href, data.get('rep', data))

    def _merge(self, href, rep):
        if not isinstance(rep, dict) or not rep:
            raise ConnectionError('O aparelho não informou o estado do recurso.')
        with self._condition:
            self.resources[href] = {**self.resources.get(href, {}), **rep}
            self._versions[href] = self._versions.get(href, 0)+1
            self._reported_fields[href] = set(rep)
            self._condition.notify_all()
            return self.snapshot()

    def read_resource(self, href, timeout=2):
        if href in self._unsupported_reads:
            return self.refresh()
        with self._condition:
            revision = self._versions.get(href, 0)
        try:
            data = self.read(href, timeout=timeout)
        except ResourceUnavailable:
            self._unsupported_reads.add(href)
            return self.refresh()
        rep = self._representation(href, data)
        with self._condition:
            if self._versions.get(href, 0) != revision:
                return self.snapshot()
            return self._merge(href, rep)

    def _notification(self, generation, href, body):
        if generation != self._generation or not self.session:
            return
        try:
            rep = self._representation(href, cbor2.loads(body))
            with self._condition:
                if href not in self.resources:
                    return
                state = self._merge(href, rep)
                self._observed.add(href)
                self._last_contact = time.monotonic()
            LOG.info('[latency] stage=notification path=%s', href)
            if self.on_change:
                self.on_change(state)
        except Exception as error:
            LOG.warning('observe path=%s error=%s', href, type(error).__name__)

    def _status_paths(self):
        candidates = ('/power/vs/0', '/power/0', MODE, '/temperature/desired/0',
                      '/temperatures/vs/0', FAN, SWING, PRESET,
                      '/modeoption/windfree/vs/0', '/light/vs/0', '/temperature/current/0')
        with self._condition:
            return [href for href in candidates if href in self.resources]

    def poll(self):
        paths = self._status_paths()
        if not paths:
            return self.refresh()
        unobserved = [href for href in paths if href not in self._observed]
        paths = unobserved or paths
        href = paths[self._poll_index % len(paths)]
        self._poll_index += 1
        return self.read_resource(href)

    def poll_needed(self):
        paths = self._status_paths()
        return not paths or any(href not in self._observed for href in paths) or time.monotonic()-self._last_contact >= 15

    def _progress(self, message):
        if self.on_progress:
            self.on_progress(message)

    @staticmethod
    def _matches(state, kind, value):
        observed = getattr(state, kind)
        return abs(observed-float(value)) < .05 if kind == 'temperature' and observed is not None else observed == value

    @staticmethod
    def _confirmation_field(kind, path):
        if kind == 'display_light': return V+'options' if path == MODE else 'mode'
        if kind == 'power': return V+'power' if path == '/power/vs/0' else 'value'
        if kind == 'temperature': return 'temperature' if path == '/temperature/desired/0' else V+'items'
        if kind == 'windfree' and path == '/modeoption/windfree/vs/0': return V+'windfree'
        return V+'modes'

    def command(self, kind: str, value, request_id=None) -> State:
        if not self.session:
            raise ConnectionError('Sem conexão com o ar-condicionado.')
        started = time.perf_counter(); request_id = request_id or uuid4().hex[:8]
        LOG.info('[latency] id=%s kind=%s stage=requested', request_id, kind)
        if not self.resources:
            self.refresh()
        enabling_nano = (kind == 'windfree' and value) or (kind == 'preset' and value in ('Nano', 'NanoSleep'))
        required = []
        if kind not in ('power', 'display_light'):
            required.append('/power/vs/0' if '/power/vs/0' in self.resources else '/power/0')
        if enabling_nano:
            required.extend((MODE, PRESET))
        for href in required:
            if href in self.resources and href not in self._observed:
                self.read_resource(href)
        before = self.snapshot()
        if kind not in ('power', 'display_light') and before.power is False:
            raise ValueError('Ligue o aparelho antes de ajustar a climatização.')
        if enabling_nano and before.mode not in ('Cool', 'Dry'):
            raise ValueError('Para ativar WindFree, selecione Resfriar ou Desumidificar primeiro.')
        with self._condition:
            path, payload = command_payload(kind, value, self.resources)
            revision = self._versions.get(path, 0)
        field = self._confirmation_field(kind, path)
        prepared = time.perf_counter()
        self._progress('Enviando comando…')
        LOG.info('[latency] id=%s kind=%s stage=post_started elapsed_ms=%.1f',
                 request_id, kind, (prepared-started)*1000)
        code, _ = self.session.post(path.strip('/').split('/'), cbor2.dumps(payload), timeout=3)
        acknowledged = time.perf_counter()
        if code >> 5 != 2:
            raise RuntimeError(f'O aparelho recusou o comando (CoAP {code >> 5}.{code & 31:02d}).')
        self._last_contact = time.monotonic()
        LOG.info('[latency] id=%s kind=%s stage=ack duration_ms=%.1f elapsed_ms=%.1f',
                 request_id, kind, (acknowledged-prepared)*1000, (acknowledged-started)*1000)
        self._progress('Comando recebido · conferindo estado…')
        deadline = time.monotonic()+5
        for attempt, delay in enumerate((0, .05, .1, .2, .4, .8, 1, 1), 1):
            if attempt == 1 and path in self._observed:
                with self._condition:
                    self._condition.wait_for(
                        lambda: (self._versions.get(path, 0) > revision
                                 and field in self._reported_fields.get(path, set())
                                 and self._matches(self.snapshot(), kind, value)), timeout=.65)
            elif delay:
                if path in self._observed:
                    with self._condition:
                        self._condition.wait(min(delay, max(0, deadline-time.monotonic())))
                else:
                    time.sleep(delay)
            with self._condition:
                state = self.snapshot()
                confirmed = (self._versions.get(path, 0) > revision
                             and field in self._reported_fields.get(path, set())
                             and self._matches(state, kind, value))
            source = 'notification'
            if not confirmed:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    break
                state = self.read_resource(path, timeout=min(2, remaining))
                confirmed = field in self._reported_fields.get(path, set()) and self._matches(state, kind, value)
                source = 'readback'
            if confirmed:
                elapsed = (time.perf_counter()-started)*1000
                self.last_timing = {'kind': kind, 'total_ms': elapsed,
                    'prepare_ms': (prepared-started)*1000,
                    'post_ms': (acknowledged-prepared)*1000,
                    'confirm_ms': (time.perf_counter()-acknowledged)*1000, 'source': source}
                LOG.info('[latency] id=%s kind=%s stage=confirmed source=%s attempt=%s total_ms=%.1f',
                         request_id, kind, source, attempt, elapsed)
                return state
        LOG.warning('[latency] id=%s kind=%s stage=not_confirmed total_ms=%.1f',
                    request_id, kind, (time.perf_counter()-started)*1000)
        raise RuntimeError('O aparelho recebeu o comando, mas não confirmou a alteração. Confira o modo e tente novamente.')
