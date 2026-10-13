"""Capability-driven control; no commands are inferred from a model name."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
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
    # Samsung's Light token represents display-off mode, so its polarity is inverted.
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
            # The appliance merges this single option; do not resend sleep, sound or mode settings.
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
        # NanoSleep preserves an active sleep timer rather than cancelling it.
        preset = 'NanoSleep' if value and state.preset in ('Sleep', 'NanoSleep') else ('Nano' if value else 'Off')
        if preset not in state.presets:
            raise ValueError('WindFree indisponível neste estado.')
        return PRESET, {V + 'modes': preset}
    raise ValueError('Controle indisponível neste aparelho.')


class Device:
    def __init__(self):
        self.session = None
        self.info = {}
        self.resources = {}

    def close(self):
        if self.session:
            self.session.close()
            self.session = None

    def connect(self, host: str, expected_id: str | None = None, port: int | None = None) -> dict:
        validate_host(host)
        # Remembered secure endpoints avoid public discovery replies from changing
        # source ports, which Windows Firewall can block for a new executable.
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
        session = DtlsCoapSession(host, info['port'], cert_pem=identity['cert'], key_pem=identity['key'])
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
            self.refresh()
        except Exception:
            session.close()
            self.session = None
            raise
        return info

    def read(self, path: str):
        if not self.session:
            raise ConnectionError('Sem conexão com o ar-condicionado.')
        code, body = self.session.get(path.strip('/').split('/'), timeout=8)
        if code >> 5 != 2:
            raise ConnectionError(f'O aparelho recusou a leitura (CoAP {code >> 5}.{code & 31:02d}).')
        return cbor2.loads(body) if body else {}

    def refresh(self) -> State:
        resources = flatten_resources(self.read('/device/0'))
        if not resources or MODE not in resources:
            raise ConnectionError('O aparelho não informou os controles de climatização.')
        self.resources = resources
        return state_from_resources(resources)

    def command(self, kind: str, value) -> State:
        if not self.session:
            raise ConnectionError('Sem conexão com o ar-condicionado.')
        # Re-read before writes: the physical remote/SmartThings may have changed state.
        before = self.refresh()
        if kind not in ('power', 'display_light') and before.power is False:
            raise ValueError('Ligue o aparelho antes de ajustar a climatização.')
        enabling_nano = (kind == 'windfree' and value) or (kind == 'preset' and value in ('Nano', 'NanoSleep'))
        if enabling_nano and before.mode not in ('Cool', 'Dry'):
            raise ValueError('Para ativar WindFree, selecione Resfriar ou Desumidificar primeiro.')
        path, payload = command_payload(kind, value, self.resources)
        code, _ = self.session.post(path.strip('/').split('/'), cbor2.dumps(payload), timeout=8)
        if code >> 5 != 2:
            raise RuntimeError(f'O aparelho recusou o comando (CoAP {code >> 5}.{code & 31:02d}).')
        # Samsung may ACK and silently ignore a command. Confirm readback after its settling period.
        for delay in (1.0, 3.0):
            time.sleep(delay)
            state = self.refresh()
            observed = getattr(state, kind)
            equal = abs(observed - float(value)) < 0.05 if kind == 'temperature' and observed is not None else observed == value
            if equal:
                return state
        raise RuntimeError('O aparelho recebeu o comando, mas não confirmou a alteração. Confira o modo e tente novamente.')
