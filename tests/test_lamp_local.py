"""Local Tuya fixtures validate actual DP encoding without a real device key."""
import copy
import pytest
import tinytuya
from lamp.local import LocalLamp, discover_local
from lamp.state import matches

DPS = {'20': True, '21': 'white', '22': 600, '23': 200, '24': '00b403e80258'}
INFO = {'provider': 'local', 'device_id': 'testlamp01', 'host': '192.168.15.11', 'version': 3.5}
KEY = 'fixturelocalkey1'


class Bulb:
    def __init__(self, responses):
        self.responses = list(responses); self.payloads = []; self.closed = False
        self.dpset = {key: str(value) if key in ('switch', 'mode', 'brightness', 'colourtemp', 'colour') else value
                      for key, value in tinytuya.BulbDevice.DEFAULT_DPSET['B'].items()}
        self.bulb_configured = True
    def set_socketTimeout(self, _): pass
    def set_socketRetryLimit(self, _): pass
    def set_socketPersistent(self, _): pass
    def set_sendWait(self, _): pass
    def set_version(self, version): self.version = version
    def status(self):
        if len(self.responses) > 1: return self.responses.pop(0)
        return self.responses[0]
    def set_multiple_values(self, payload, nowait=False): self.payloads.append(payload); return {}
    def close(self): self.closed = True


def local(responses):
    bulb = Bulb(responses); device = LocalLamp(factory=lambda *_: bulb, sleep=lambda _: None)
    device.connect(INFO, KEY)
    return device, bulb


def read(dps=DPS): return {'dps': copy.deepcopy(dps)}


def test_local_reads_native_percentage_and_active_mode():
    device, bulb = local([read()])
    assert bulb.version == 3.5
    assert device.state.power is True and device.state.level == 60
    assert device.state.kelvin == 20 and device.state.white_unit == '%'
    assert device.state.color_mode == 'white'
    assert device.state.minimum_level == 1


def test_brightness_in_color_mode_comes_from_hsv_not_retained_white_dp():
    dps = {**DPS, '21': 'colour', '24': '00b403e80190'}
    device, _ = local([read(dps)])
    assert device.state.level == 40 and device.state.color_mode == 'color'
    assert device.state.hue == 50


@pytest.mark.parametrize('key', ['', '123', 'this-key-is-too-long'])
def test_invalid_local_key_does_not_open_connection(key):
    device = LocalLamp(factory=lambda *_: pytest.fail('must not connect'))
    with pytest.raises(ValueError, match='16 bytes'): device.connect(INFO, key)


def test_discovery_is_read_only_and_does_not_load_or_return_secrets(monkeypatch):
    def scan(**kwargs):
        assert kwargs['poll'] is False and kwargs['forcescan'] is False
        assert kwargs['tuyadevices']
        return {'192.168.15.11': {'gwId': 'testlamp01', 'version': '3.5', 'key': 'DO-NOT-RETURN'}}
    monkeypatch.setattr('tinytuya.scanner.devices', scan)
    result = discover_local()
    assert result[0]['device_id'] == 'testlamp01' and 'key' not in result[0]
    assert discover_local('other-id') == []


def test_local_power_command_requires_readback():
    changed = {**DPS, '20': False}
    device, bulb = local([read(), read(), read(changed)])
    assert device.command('power', False).power is False
    assert bulb.payloads == [{'20': False}]


def test_white_adjustment_encodes_percentage_and_mode_without_touching_rgb():
    changed = {**DPS, '23': 750}
    device, bulb = local([read(), read(), read(changed)])
    assert device.command('kelvin', 75).kelvin == 75
    assert bulb.payloads == [{'23': 750, '21': 'white'}]


@pytest.mark.parametrize('temperature', [0, 29, 100])
def test_white_presets_use_white_channels_preserving_brightness_and_rgb(temperature):
    changed = {**DPS, '23': temperature*10}
    device, bulb = local([read(), read(), read(changed)])
    state = device.command('kelvin', temperature)
    assert state.level == 60 and state.color_mode == 'white'
    assert bulb.payloads == [{'23': temperature*10, '21': 'white'}]


def test_returning_to_white_preserves_rgb_brightness_instead_of_cached_white_level():
    initial = {**DPS, '21': 'colour', '24': '00b403e80190'}
    changed = {**initial, '21': 'white', '22': 400, '23': 290}
    device, bulb = local([read(initial), read(initial), read(changed)])
    state = device.command('kelvin', 29)
    assert state.level == 40 and state.color_mode == 'white'
    assert bulb.payloads == [{'23': 290, '21': 'white', '22': 400}]


def test_white_readback_tolerance_is_percentage_not_kelvin():
    device, _ = local([read()])
    assert not matches(device.state, 'kelvin', 60)


def test_rgb_command_preserves_confirmed_brightness():
    changed = {**DPS, '21': 'colour', '24': '005a01f40258'}
    device, bulb = local([read(), read(), read(changed)])
    state = device.command('color', {'hue': 25, 'saturation': 50})
    assert state.level == 60 and state.color_mode == 'color'
    assert bulb.payloads == [{'24': '005a01f40258', '21': 'colour'}]


def test_brightness_in_rgb_keeps_color():
    initial = {**DPS, '21': 'colour'}
    changed = {**initial, '24': '00b403e80320'}
    device, bulb = local([read(initial), read(initial), read(changed)])
    assert device.command('level', 80).level == 80
    assert bulb.payloads == [{'24': '00b403e80320', '21': 'colour'}]


def test_local_ack_without_change_reports_error():
    device, _ = local([read()]*5)
    with pytest.raises(RuntimeError, match='não confirmou'): device.command('kelvin', 75)
    assert device.state.kelvin == 20


def test_wrong_device_cannot_be_controlled_as_rgb_lamp():
    with pytest.raises(ValueError): local([{'dps': {'1': True}}])


def test_invalid_key_error_is_sanitized():
    with pytest.raises(RuntimeError) as caught: local([{'Error': KEY, 'Err': '914'}])
    assert KEY not in str(caught.value)


def test_local_white_mode_must_also_be_confirmed():
    retained = {**DPS, '21': 'colour'}
    device, _ = local([read(retained)]*5)
    with pytest.raises(RuntimeError, match='não confirmou'): device.command('kelvin', 20)


def test_one_percent_adjustment_requires_changed_native_value():
    device, _ = local([read()]*5)
    with pytest.raises(RuntimeError, match='não confirmou'): device.command('kelvin', 21)


def test_first_confirmation_has_no_compulsory_sleep():
    changed = {**DPS, '22': 650}
    device, _ = local([read(), read(changed)])
    delays = []; device.sleep = delays.append
    assert device.command('level', 65).level == 65
    assert delays == []


def test_partial_hardware_reply_confirms_brightness_without_losing_other_fields():
    device, bulb = local([read(), {'dps': {'22': 650}}])
    state = device.command('level', 65)
    assert state.level == 65 and state.power and state.color_mode == 'white'
    assert device.dps['24'] == DPS['24']
    assert bulb.responses == [{'dps': {'22': 650}}]


def test_cached_value_alone_cannot_confirm_a_repeated_command():
    device, _ = local([read()] + [{'dps': {'22': 600}}]*10)
    with pytest.raises(RuntimeError, match='não confirmou'): device.command('kelvin', 20)


def test_expired_cache_reads_current_mode_before_encoding(monkeypatch):
    rgb = {**DPS, '21': 'colour'}
    changed = {**rgb, '24': '00b403e80320'}
    device, bulb = local([read(), read(rgb), read(changed)])
    monkeypatch.setattr('lamp.local.time.monotonic', lambda: 10**12)
    assert device.command('level', 80).color_mode == 'color'
    assert bulb.payloads == [{'24': '00b403e80320', '21': 'colour'}]


def test_power_sends_without_preflight_even_after_idle(monkeypatch):
    device, _ = local([read(), {'dps': {'20': False}}])
    monkeypatch.setattr('lamp.local.time.monotonic', lambda: 10**12)
    assert device.command('power', False).power is False


class Notifications(Bulb):
    def __init__(self, responses, notifications):
        super().__init__(responses)
        self.notifications = list(notifications)
        self.retry = True; self.connection_timeout = 3
    def set_retry(self, retry): self.retry = retry
    def set_socketTimeout(self, timeout): self.connection_timeout = timeout
    def receive(self): return self.notifications.pop(0) if self.notifications else None


def test_empty_ack_is_followed_by_actual_notification_without_delay():
    bulb = Notifications([read()], [None, {'dps': {'22': 650}}])
    delays = []; device = LocalLamp(factory=lambda *_: bulb, sleep=delays.append)
    device.connect(INFO, KEY)
    assert device.command('level', 65).level == 65 and delays == []
    assert bulb.retry is True and bulb.connection_timeout == 3


def test_missing_notifications_fall_back_to_full_status():
    bulb = Notifications([read(), read({**DPS, '22': 650})], [])
    device = LocalLamp(factory=lambda *_: bulb, sleep=lambda _: None)
    device.connect(INFO, KEY)
    assert device.command('level', 65).level == 65


def test_buffered_old_notification_cannot_confirm_new_command(monkeypatch):
    bulb = Notifications([read()], [{'dps': {'22': 650}}] + [{'dps': {'23': 200}}]*7)
    bulb.socket = object(); checks = iter([([bulb.socket], [], []), ([], [], [])])
    monkeypatch.setattr('lamp.local.select.select', lambda *_: next(checks))
    device = LocalLamp(factory=lambda *_: bulb, sleep=lambda _: None)
    device.connect(INFO, KEY)
    with pytest.raises(RuntimeError, match='não confirmou'): device.command('level', 65)
    assert bulb.payloads == [{'22': 650}]


def test_notification_errors_never_expose_key():
    bulb = Notifications([read()], [{'Error': KEY}])
    device = LocalLamp(factory=lambda *_: bulb)
    device.connect(INFO, KEY)
    with pytest.raises(RuntimeError) as caught: device.command('power', False)
    assert KEY not in str(caught.value)
    assert bulb.retry is True and bulb.connection_timeout == 3


def test_session_is_released_so_another_client_can_use_the_lamp():
    device, bulb = local([read()])
    device.release()
    assert bulb.closed
    assert device.refresh().power is True
