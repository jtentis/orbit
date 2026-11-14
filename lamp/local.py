"""Tuya LAN adapter. Discovery is public; encrypted control needs a local key."""
import math
import logging
import select
import time
from uuid import uuid4
import tinytuya
import tinytuya.scanner
from shared.network import validate_host
from .state import LampState, command_payload, matches

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


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
        self.read_at = 0.; self.updated_dps = set()
        self.on_progress = None

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
        candidate.set_socketPersistent(True); candidate.set_sendWait(0); candidate.set_version(version)
        previous = self.bulb, self.state, self.info, self.key, self.dps, self.read_at, self.updated_dps
        self.bulb, self.info, self.key = candidate, {**info, 'version': version}, key
        self.state = None; self.dps = {}; self.read_at = 0.; self.updated_dps = set()
        try: result = self.refresh()
        except Exception:
            candidate.close()
            self.bulb, self.state, self.info, self.key, self.dps, self.read_at, self.updated_dps = previous
            raise
        if previous[0]: previous[0].close()
        return result

    def refresh(self):
        if not self.bulb: raise ValueError('Conecte a lâmpada com sua chave local.')
        try: response = self.bulb.status()
        except Exception:
            raise RuntimeError('Lâmpada sem resposta local. Confira a rede, o IP e a chave local.') from None
        return self._accept(response)

    def _accept(self, response):
        if isinstance(response, dict) and 'Error' in response:
            raise RuntimeError(f'A lâmpada respondeu com erro {response.get("Err")}. Confira a chave local, a rede e se outro app está usando a lâmpada.')
        if not isinstance(response, dict) or not isinstance(response.get('dps'), dict) or not response['dps']:
            raise RuntimeError('Não foi possível ler a lâmpada. Confira a chave local e a conexão Wi-Fi.')
        received = response['dps']
        dps = {**self.dps, **received}
        self.state = self.parse(dps)
        self.dps = dps
        self.updated_dps = set(received)
        self.read_at = time.monotonic()
        return self.state

    def _drain_pending(self):
        for _ in range(16):
            connection = getattr(self.bulb, 'socket', None)
            if not connection or not select.select([connection], [], [], 0)[0]: return
            response = self._receive_update()
            if response is not None: self._accept(response)
        raise RuntimeError('A lâmpada está enviando muitas atualizações. Tente novamente.')

    def _receive_update(self):
        retry = self.bulb.retry
        timeout = self.bulb.connection_timeout
        self.bulb.set_retry(False); self.bulb.set_socketTimeout(.25)
        try: return self.bulb.receive()
        finally:
            self.bulb.set_retry(retry); self.bulb.set_socketTimeout(timeout)

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

    def command(self, kind, value, request_id=None):
        started = time.perf_counter(); request_id = request_id or uuid4().hex[:8]
        LOG.info('[latency] id=%s kind=%s stage=requested', request_id, kind)
        self._drain_pending()
        before = self.state if self.state and (kind == 'power' or time.monotonic()-self.read_at <= 2) else self.refresh()
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
        sending = time.perf_counter()
        if self.on_progress: self.on_progress('Enviando comando…')
        LOG.info('[latency] id=%s kind=%s stage=write_started elapsed_ms=%.1f', request_id, kind, (sending-started)*1000)
        try: response = self.bulb.set_multiple_values(payload, nowait=True)
        except Exception:
            raise RuntimeError('Falha ao enviar o ajuste local à lâmpada.') from None
        if isinstance(response, dict) and 'Error' in response:
            raise RuntimeError('A lâmpada recusou o ajuste local. Confira a chave e a rede.')
        LOG.info('[latency] id=%s kind=%s stage=sent duration_ms=%.1f elapsed_ms=%.1f',
                 request_id, kind, (time.perf_counter()-sending)*1000, (time.perf_counter()-started)*1000)
        if self.on_progress: self.on_progress('Comando enviado · aguardando a lâmpada…')
        observed = set()
        for attempt, delay in enumerate((0, 0, 0, .1, .2, .4, .8), 1):
            if delay: self.sleep(delay)
            if self.info['version'] >= 3.4 and hasattr(self.bulb, 'receive'):
                response = self._receive_update()
                if response is None:
                    if attempt < 3: continue
                    state = self.refresh()
                else: state = self._accept(response)
            else: state = self.refresh()
            observed.update(self.updated_dps)
            expected_mode = 'white' if kind == 'kelvin' else 'color' if kind == 'color' else None
            def native_matches(dp, expected):
                actual = self.dps.get(dp)
                if dp == str(mapping.get('colour')) and isinstance(actual, str) and isinstance(expected, str):
                    return actual.lower() == expected.lower()
                return actual == expected
            written_values_confirmed = payload.keys() <= observed and all(native_matches(dp, expected) for dp, expected in payload.items())
            if written_values_confirmed and matches(state, kind, value) and (not expected_mode or state.color_mode == expected_mode):
                LOG.info('[latency] id=%s kind=%s stage=confirmed attempts=%s elapsed_ms=%.1f',
                         request_id, kind, attempt, (time.perf_counter()-started)*1000)
                return state
        LOG.warning('[latency] id=%s kind=%s stage=unconfirmed elapsed_ms=%.1f', request_id, kind, (time.perf_counter()-started)*1000)
        raise RuntimeError('O ajuste local foi enviado, mas a lâmpada não confirmou a alteração.')

    def release(self):
        """The lamp serves one local session at a time; free it so another client can use it."""
        if self.bulb: self.bulb.close()

    def close(self):
        if self.bulb: self.bulb.close()
        self.key = None
