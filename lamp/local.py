"""Tuya LAN adapter. Discovery is public; encrypted control needs a local key."""
import math
import time
import tinytuya
import tinytuya.scanner
from shared.network import validate_host
from .state import LampState, command_payload, matches


def discover_local(expected_id=None):
    devices = tinytuya.scanner.devices(verbose=False, scantime=8, poll=False,
                forcescan=False, show_timer=False, wantids=[expected_id] if expected_id else None,
                tuyadevices=[{'id': '', 'name': '', 'key': ''}])
    found = []
    for host, data in devices.items():
        device_id = data.get('gwId') or data.get('id')
        if not device_id or (expected_id and device_id != expected_id): continue
        try: host = validate_host(host); version = float(data.get('version', 0))
        except (ValueError, TypeError): continue
        if version not in (3.1, 3.2, 3.3, 3.4, 3.5): continue
        found.append({'provider': 'local', 'device_id': device_id, 'host': host,
                      'version': version, 'name': 'Dispositivo Tuya · '+host})
    return found


class LocalLamp:
    def __init__(self, factory=tinytuya.BulbDevice, sleep=time.sleep):
        self.factory, self.sleep = factory, sleep
        self.bulb = None; self.state = None; self.info = None; self.key = None; self.dps = {}

    def connect(self, info, key):
        host = validate_host(info.get('host', ''))
        device_id = str(info.get('device_id', ''))
        if not device_id or len(device_id) > 64 or not device_id.isalnum(): raise ValueError('Identidade Tuya inválida.')
        if not isinstance(key, str) or len(key.encode('utf-8')) != 16:
            raise ValueError('A chave local Tuya deve ter 16 bytes.')
        version = float(info.get('version', 3.5))
        if version not in (3.1, 3.2, 3.3, 3.4, 3.5): raise ValueError('Versão Tuya não suportada.')
        candidate = self.factory(device_id, host, key)
        candidate.set_socketTimeout(3); candidate.set_socketRetryLimit(1)
        candidate.set_socketPersistent(False); candidate.set_version(version)
        previous = self.bulb, self.state, self.info, self.key, self.dps
        self.bulb, self.info, self.key = candidate, dict(info), key
        try: result = self.refresh()
        except Exception:
            candidate.close(); self.bulb, self.state, self.info, self.key, self.dps = previous
            raise
        if previous[0]: previous[0].close()
        return result

    def refresh(self):
        if not self.bulb: raise ValueError('Conecte a lâmpada com sua chave local.')
        try: response = self.bulb.status()
        except Exception:
            raise RuntimeError('Lâmpada sem resposta local. Confira a rede, o IP e a chave local.') from None
        if not isinstance(response, dict) or 'Error' in response or not isinstance(response.get('dps'), dict):
            raise RuntimeError('Não foi possível ler a lâmpada. Confira a chave local e a conexão Wi-Fi.')
        self.state = self.parse(response['dps'])
        self.dps = dict(response['dps'])
        return self.state

    def parse(self, dps):
        mapping = self.bulb.dpset
        def raw(feature): return dps.get(str(mapping.get(feature)))
        def numeric(feature):
            value = raw(feature)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        maximum, minimum = mapping.get('value_max', -1), mapping.get('value_min', -1)
        if not self.bulb.bulb_configured or maximum <= 0 or type(raw('switch')) is not bool or not mapping.get('colour'):
            raise ValueError('O dispositivo não informou os recursos RGB esperados da SLAMP1.')
        mode = raw('mode')
        if mode not in ('white', 'colour', 'scene', 'music'):
            raise ValueError('Modo de iluminação Tuya não reconhecido.')
        caps = {'switch', 'colorControl'}
        level = numeric('brightness'); cool = numeric('colourtemp')
        if any(value is not None and not 0 <= value <= maximum for value in (level, cool)):
            raise ValueError('A lâmpada retornou ajustes fora dos limites do protocolo.')
        if level is not None:
            caps.add('switchLevel'); level = round(level/maximum*100)
        if cool is not None:
            caps.add('colorTemperature'); cool = round(cool/maximum*100)
        try:
            hue, saturation, intensity = tinytuya.BulbDevice.hexvalue_to_hsv(raw('colour'), mapping['value_hexformat'])
            if not all(math.isfinite(v) and 0 <= v <= 1 for v in (hue, saturation, intensity)): raise ValueError()
        except (ValueError, TypeError, IndexError):
            raise ValueError('A lâmpada retornou uma cor RGB inválida.') from None
        if mode == 'colour': level = round(intensity*100)
        return LampState(power=raw('switch'), level=level, kelvin=cool, hue=hue*100,
                         saturation=saturation*100, minimum_level=math.ceil(minimum/maximum*100),
                         minimum_kelvin=0, maximum_kelvin=100, capabilities=frozenset(caps),
                         color_mode='color' if mode == 'colour' else mode, health='ONLINE', white_unit='%')

    def command(self, kind, value):
        before = self.refresh()
        command_payload(kind, value, before, 'main')
        mapping = self.bulb.dpset
        maximum, minimum = mapping['value_max'], mapping['value_min']
        dp = lambda feature: str(mapping[feature])
        if kind == 'power': payload = {dp('switch'): value}
        elif kind == 'kelvin':
            payload = {dp('colourtemp'): round(value/100*maximum), dp('mode'): 'white'}
            if before.color_mode == 'color' and before.level is not None:
                payload[dp('brightness')] = max(minimum, round(before.level/100*maximum))
        elif kind in ('level', 'color'):
            if kind == 'level' and before.color_mode == 'white':
                payload = {dp('brightness'): max(minimum, round(value/100*maximum))}
            else:
                if kind == 'level' and before.color_mode != 'color':
                    raise ValueError('Ajuste o branco ou a cor antes de alterar o brilho neste modo.')
                h = value['hue'] if kind == 'color' else before.hue
                s = value['saturation'] if kind == 'color' else before.saturation
                brightness = value if kind == 'level' else before.level
                if brightness is None: raise ValueError('O brilho atual da lâmpada ainda não foi informado.')
                encoded = tinytuya.BulbDevice.hsv_to_hexvalue(h/100, s/100, max(minimum/maximum, brightness/100), mapping['value_hexformat'])
                payload = {dp('colour'): encoded, dp('mode'): 'colour'}
        try: response = self.bulb.set_multiple_values(payload)
        except Exception:
            raise RuntimeError('Falha ao enviar o ajuste local à lâmpada.') from None
        if isinstance(response, dict) and 'Error' in response:
            raise RuntimeError('A lâmpada recusou o ajuste local. Confira a chave e a rede.')
        for delay in (.3, .7, 1.5):
            self.sleep(delay); state = self.refresh()
            expected_mode = 'white' if kind == 'kelvin' else 'color' if kind == 'color' else None
            def native_matches(dp, expected):
                actual = self.dps.get(dp)
                if dp == str(mapping.get('colour')) and isinstance(actual, str) and isinstance(expected, str):
                    return actual.lower() == expected.lower()
                return actual == expected
            written_values_confirmed = all(native_matches(dp, expected) for dp, expected in payload.items())
            if written_values_confirmed and matches(state, kind, value) and (not expected_mode or state.color_mode == expected_mode):
                return state
        raise RuntimeError('O ajuste local foi enviado, mas a lâmpada não confirmou a alteração.')

    def close(self):
        if self.bulb: self.bulb.close()
        self.key = None
