from __future__ import annotations
import math
import time
from urllib.parse import urlparse, quote
import requests
from .state import LampState, command_payload, matches, confirmed_change


API = 'https://api.smartthings.com/v1'


TOKEN_PAGE = 'https://account.smartthings.com/tokens'


class AuthorizationError(RuntimeError):
    pass


def lighting_components(device):
    """Exclude sockets/AC switches; retain the component actually advertising light."""
    result = []
    for component in device.get('components', []):
        caps = {cap['id'] for cap in component.get('capabilities', [])}
        categories = {category.get('name') for category in component.get('categories', [])}
        signature = ' '.join(str(device.get(key, '')) for key in ('name', 'label', 'manufacturerName')).lower()
        is_light = bool(caps & {'colorControl', 'colorTemperature'}) or 'Light' in categories or 'slamp1' in signature
        if 'switch' in caps and is_light:
            result.append(component)
    return result


def state_from_status(status, component, capabilities, health='UNKNOWN'):
    data = status.get('components', {}).get(component, {})
    def value(cap, attribute):
        return data.get(cap, {}).get(attribute, {}).get('value')
    def number(cap, attribute, low, high):
        raw = value(cap, attribute)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw) and low <= raw <= high:
            return raw
        return None
    def bounds(cap, attribute, defaults, low, high):
        raw = value(cap, attribute)
        if isinstance(raw, dict):
            a, b = raw.get('minimum'), raw.get('maximum')
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (a, b)) and low <= a < b <= high:
                return math.ceil(a), math.floor(b)
        return defaults
    level_range = bounds('switchLevel', 'levelRange', (1, 100), 0, 100)
    kelvin_range = bounds('colorTemperature', 'colorTemperatureRange', (2000, 6500), 1000, 15000)
    power = value('switch', 'switch')
    mode = value('colorMode', 'colorMode')
    return LampState(
        power={'on': True, 'off': False}.get(power),
        level=number('switchLevel', 'level', 0, 100),
        kelvin=number('colorTemperature', 'colorTemperature', 1000, 15000),
        hue=number('colorControl', 'hue', 0, 100),
        saturation=number('colorControl', 'saturation', 0, 100),
        minimum_level=level_range[0], maximum_level=level_range[1],
        minimum_kelvin=kelvin_range[0], maximum_kelvin=kelvin_range[1],
        capabilities=frozenset(capabilities), color_mode=mode, health=health,
        white_timestamp=data.get('colorTemperature', {}).get('colorTemperature', {}).get('timestamp'),
        color_timestamps=tuple(data.get('colorControl', {}).get(attribute, {}).get('timestamp') for attribute in ('hue', 'saturation')),
    )


class SmartThingsLamp:
    def __init__(self, session=None, sleep=time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep
        self.token = None
        self.device_id = None
        self.component = None
        self.capabilities = frozenset()
        self.state = None
        self.retry_at = 0

    def authorize(self, token):
        token = token.strip()
        if not token or len(token) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError('Cole um token SmartThings válido.')
        self.token = token
        self.retry_at = 0

    def request(self, method, path, payload=None):
        if not self.token: raise AuthorizationError('Conecte sua conta SmartThings para acessar a lâmpada.')
        if time.monotonic() < self.retry_at: raise RuntimeError('SmartThings limitou as consultas. Aguarde antes de tentar novamente.')
        url = API + path if path.startswith('/') else path
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'api.smartthings.com' or not parsed.path.startswith('/v1/'):
            raise RuntimeError('Endereço de resposta SmartThings inválido.')
        try:
            response = self.session.request(method, url, headers={'Authorization': 'Bearer '+self.token, 'Accept': 'application/json'},
                                            json=payload, timeout=(5, 8), allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError('Sem resposta do SmartThings. Confira a conexão com a internet.') from None
        if response.status_code == 401:
            raise AuthorizationError('Token expirado ou inválido. Gere outro token em Conectar SmartThings.')
        if response.status_code == 403:
            raise AuthorizationError('Token sem permissão. Autorize listar, ler e controlar dispositivos.')
        if response.status_code == 404: raise RuntimeError('Lâmpada não encontrada nesta conta. Escolha novamente o dispositivo.')
        if response.status_code == 429:
            try: delay = float(response.headers.get('Retry-After', 60))
            except (TypeError, ValueError): delay = 60
            self.retry_at = time.monotonic() + (min(3600, max(10, delay)) if math.isfinite(delay) else 60)
            raise RuntimeError('SmartThings limitou as consultas. Aguarde antes de tentar novamente.')
        if response.status_code >= 500: raise RuntimeError('SmartThings indisponível. Tente novamente em instantes.')
        if not 200 <= response.status_code < 300: raise RuntimeError('SmartThings recusou a solicitação. Confira os recursos da lâmpada.')
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError('SmartThings retornou uma resposta inválida.') from None
        if not isinstance(data, dict): raise RuntimeError('Resposta SmartThings inesperada.')
        return data

    def discover(self):
        result, path, seen = [], '/devices?capability=switch', set()
        while path:
            if path in seen or len(seen) >= 20: raise RuntimeError('Lista de dispositivos incompleta. Tente novamente.')
            seen.add(path)
            data = self.request('GET', path)
            for item in data.get('items', []):
                for component in lighting_components(item):
                    name = item.get('label') or item.get('name') or 'Lâmpada'
                    if component['id'] != 'main': name += ' · '+component.get('label', component['id'])
                    result.append({'device_id': item['deviceId'], 'component': component['id'], 'name': name})
            path = data.get('_links', {}).get('next', {}).get('href')
        return result

    def connect(self, info):
        device_id = str(info.get('device_id', ''))
        detail = self.request('GET', '/devices/'+quote(device_id, safe=''))
        components = lighting_components(detail)
        component = next((c for c in components if c['id'] == info.get('component', 'main')), None)
        if not component: raise ValueError('O dispositivo escolhido não anuncia recursos de iluminação.')
        previous = (self.device_id, self.component, self.capabilities, self.state)
        self.device_id, self.component = device_id, component['id']
        self.capabilities = frozenset(c['id'] for c in component['capabilities'])
        try:
            return self.refresh()
        except Exception:
            self.device_id, self.component, self.capabilities, self.state = previous
            raise

    def refresh(self):
        if not self.device_id: raise ValueError('Escolha sua SLAMP1 na lista de lâmpadas.')
        base = '/devices/'+quote(self.device_id, safe='')
        health = self.request('GET', base+'/health').get('state', 'UNKNOWN')
        if health in ('OFFLINE', 'UNHEALTHY'): raise RuntimeError('Lâmpada sem conexão no SmartThings. Confira se ela está energizada.')
        status = self.request('GET', base+'/status')
        self.state = state_from_status(status, self.component, self.capabilities, health)
        if self.state.power is None: raise RuntimeError('SmartThings ainda não informou o estado da lâmpada.')
        return self.state

    def command(self, kind, value):
        state = self.refresh()
        before = state
        payload = command_payload(kind, value, state, self.component)
        if kind in ('power', 'level') and matches(state, kind, value): return state
        response = self.request('POST', '/devices/'+quote(self.device_id, safe='')+'/commands', payload)
        results = response.get('results', [])
        if len(results) != len(payload['commands']) or any(r.get('status') not in ('ACCEPTED', 'COMPLETED') for r in results):
            raise RuntimeError('SmartThings não aceitou o ajuste de iluminação.')
        for delay in (1, 2, 3):
            self.sleep(delay)
            state = self.refresh()
            if confirmed_change(before, state, kind, value): return state
        raise RuntimeError('O ajuste foi enviado, mas o SmartThings não confirmou a alteração.')

    def close(self):
        self.token = None
        self.session.close()
