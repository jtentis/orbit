"""Protocol fixtures exercise actual HTTP mapping without changing hardware."""
import copy
import pytest
from lamp.state import LampState, command_payload, matches
from lamp.smartthings import SmartThingsLamp, AuthorizationError, lighting_components, state_from_status

CAPS = frozenset({'switch', 'switchLevel', 'colorTemperature', 'colorControl'})
DETAIL = {'deviceId': 'lamp-id', 'label': 'SLAMP1', 'components': [
    {'id': 'main', 'capabilities': [{'id': cap} for cap in CAPS]}]}
STATUS = {'components': {'main': {
    'switch': {'switch': {'value': 'on'}},
    'switchLevel': {'level': {'value': 60}, 'levelRange': {'value': {'minimum': 1, 'maximum': 100}}},
    'colorTemperature': {'colorTemperature': {'value': 3000}, 'colorTemperatureRange': {'value': {'minimum': 2700, 'maximum': 6500}}},
    'colorControl': {'hue': {'value': 60}, 'saturation': {'value': 100}},
}}}


class Response:
    def __init__(self, data, code=200, headers=None):
        self.data, self.status_code, self.headers = data, code, headers or {}
    def json(self): return copy.deepcopy(self.data)


class Session:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs)); return self.responses.pop(0)
    def close(self): pass


def adapter(responses):
    session = Session(responses); device = SmartThingsLamp(session, sleep=lambda _: None)
    device.authorize('fixture-secret-token'); device.device_id = 'lamp-id'; device.component = 'main'; device.capabilities = CAPS
    return device, session


def reads(status=STATUS, health='ONLINE'):
    return [Response({'state': health}), Response(status)]


def test_advertised_ranges_and_smartthings_units():
    state = state_from_status(STATUS, 'main', CAPS)
    assert state.power is True and state.hue == 60
    assert (state.minimum_kelvin, state.maximum_kelvin) == (2700, 6500)
    assert state.color_mode is None  # Retained hue doesn't prove RGB mode.
    assert command_payload('color', {'hue': 60, 'saturation': 100}, state, 'main')['commands'][0] == {
        'component': 'main', 'capability': 'colorControl', 'command': 'setColor', 'arguments': [{'hue': 60, 'saturation': 100}]}


@pytest.mark.parametrize('kind,value', [('level', 101), ('kelvin', 2600), ('level', True), ('level', float('nan')),
    ('power', 1), ('color', {'hue': 360, 'saturation': 100}), ('color', {'hue': 10}), ('unknown', 1)])
def test_invalid_values_never_generate_commands(kind, value):
    with pytest.raises(ValueError): command_payload(kind, value, state_from_status(STATUS, 'main', CAPS), 'main')


def test_missing_capability_and_power_off_guard():
    with pytest.raises(ValueError): command_payload('level', 50, LampState(power=True, capabilities=frozenset({'switch'})), 'main')
    with pytest.raises(ValueError): command_payload('color', {'hue': 40, 'saturation': 90}, LampState(power=False, capabilities=CAPS), 'main')
    assert command_payload('power', True, LampState(power=False, capabilities=CAPS), 'main')['commands'][0]['command'] == 'on'


def test_discovery_excludes_ac_and_sockets_but_keeps_actual_light_component():
    socket = {'name': 'Socket', 'components': [{'id': 'main', 'categories': [{'name': 'SmartPlug'}], 'capabilities': [{'id': 'switch'}]}]}
    assert lighting_components(socket) == []
    detail = copy.deepcopy(DETAIL); detail['components'][0]['id'] = 'light1'
    assert lighting_components(detail)[0]['id'] == 'light1'


def test_paginated_discovery_and_https_credentials():
    device, session = adapter([Response({'items': [DETAIL], '_links': {'next': {'href': 'https://api.smartthings.com/v1/devices?page=2'}}}), Response({'items': []})])
    assert device.discover() == [{'device_id': 'lamp-id', 'component': 'main', 'name': 'SLAMP1'}]
    assert len(session.calls) == 2
    assert all(call[1]['allow_redirects'] is False for call in session.calls)
    assert session.calls[0][1]['headers']['Authorization'] == 'Bearer fixture-secret-token'


def test_untrusted_pagination_cannot_receive_token():
    device, session = adapter([Response({'items': [], '_links': {'next': {'href': 'https://evil.example/v1/devices'}}})])
    with pytest.raises(RuntimeError, match='Endereço'): device.discover()
    assert len(session.calls) == 1


@pytest.mark.parametrize('code', [401, 403])
def test_auth_error_never_exposes_credentials_or_server_body(code):
    device, _ = adapter([Response({'error': 'fixture-secret-token'}, code)])
    with pytest.raises(AuthorizationError) as caught: device.discover()
    assert 'fixture-secret-token' not in str(caught.value)


def test_rate_limit_stops_additional_requests():
    device, session = adapter([Response({}, 429, {'Retry-After': '60'})])
    for _ in range(2):
        with pytest.raises(RuntimeError, match='limitou'): device.discover()
    assert len(session.calls) == 1


def test_cached_offline_device_cannot_be_commanded():
    device, session = adapter([Response({'state': 'OFFLINE'})])
    with pytest.raises(RuntimeError, match='sem conexão'): device.command('power', False)
    assert all(call[0][0] == 'GET' for call in session.calls)


def test_accepted_command_is_confirmed_only_by_readback():
    changed = copy.deepcopy(STATUS); changed['components']['main']['switchLevel']['level']['value'] = 80
    device, session = adapter(reads() + [Response({'results': [{'status': 'ACCEPTED'}]})] + reads() + reads(changed))
    result = device.command('level', 80)
    assert result.level == 80
    post = next(call for call in session.calls if call[0][0] == 'POST')
    assert post[1]['json']['commands'][0]['arguments'] == [80]


def test_accepted_but_unchanged_command_reports_failure_and_retains_real_state():
    device, _ = adapter(reads() + [Response({'results': [{'status': 'ACCEPTED'}]})] + reads()*3)
    with pytest.raises(RuntimeError, match='não confirmou'): device.command('kelvin', 4000)
    assert device.state.kelvin == 3000


def test_failed_selection_restores_previous_identity():
    detail = copy.deepcopy(DETAIL); detail['deviceId'] = 'different-id'
    device, _ = adapter([Response(detail), Response({'state': 'OFFLINE'})])
    with pytest.raises(RuntimeError): device.connect({'device_id': 'different-id', 'component': 'main'})
    assert device.device_id == 'lamp-id'


def test_non_main_component_status_and_payload():
    status = {'components': {'light1': STATUS['components']['main']}}
    state = state_from_status(status, 'light1', CAPS)
    assert state.level == 60
    assert command_payload('kelvin', 4000, state, 'light1')['commands'][0]['component'] == 'light1'


def test_hue_wrap_and_malformed_reading():
    state = LampState(hue=100, saturation=100)
    assert matches(state, 'color', {'hue': 0, 'saturation': 100})
    assert state_from_status({'components': {}}, 'main', CAPS).power is None
    malformed = copy.deepcopy(STATUS); malformed['components']['main']['switchLevel']['level']['value'] = True
    assert state_from_status(malformed, 'main', CAPS).level is None


def test_retained_white_value_requires_fresh_confirmation_when_mode_is_unknown():
    device, session = adapter(reads() + [Response({'results': [{'status': 'ACCEPTED'}]})] + reads()*3)
    with pytest.raises(RuntimeError, match='não confirmou'): device.command('kelvin', 3000)
    assert any(call[0][0] == 'POST' for call in session.calls)


def test_fresh_timestamp_confirms_switching_to_retained_white_value():
    changed = copy.deepcopy(STATUS)
    changed['components']['main']['colorTemperature']['colorTemperature']['timestamp'] = '2026-10-12T12:01:00Z'
    device, _ = adapter(reads() + [Response({'results': [{'status': 'ACCEPTED'}]})] + reads(changed))
    assert device.command('kelvin', 3000).kelvin == 3000


def test_explicit_color_mode_prevents_false_white_confirmation():
    from lamp.state import confirmed_change
    before = LampState(power=True, kelvin=3000, color_mode='color')
    after = LampState(power=True, kelvin=4000, color_mode='color')
    assert not confirmed_change(before, after, 'kelvin', 4000)
    after.color_mode = 'white'
    assert confirmed_change(before, after, 'kelvin', 4000)
