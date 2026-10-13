import copy
import json
import cbor2
from pathlib import Path
import pytest
from aircon.device import Device, command_payload, flatten_resources, state_from_resources, V, MODE, PRESET, FAN
from shared.network import validate_host


@pytest.fixture
def resources():
    return json.loads((Path(__file__).parent / 'fixtures' / 'ar12-controls.json').read_text(encoding='utf-8'))


def test_reads_real_ar12_capabilities(resources):
    state = state_from_resources(resources)
    assert state.power is False
    assert state.temperature == 24
    assert (state.minimum, state.maximum, state.step) == (16, 30, 1)
    assert state.modes == ['Auto', 'Cool', 'Dry', 'Wind']
    assert 'Heat' not in state.modes
    assert state.fans == [('0', 'Auto'), ('1', 'Low'), ('2', 'Mid'), ('3', 'High'), ('4', 'Turbo')]
    assert state.windfree is False


@pytest.mark.parametrize('value', [15, 31, float('nan'), float('inf'), 'abc'])
def test_rejects_invalid_temperature(resources, value):
    with pytest.raises(ValueError):
        command_payload('temperature', value, resources)


def test_uses_authoritative_ocf_temperature(resources):
    resources['/temperatures/vs/0'][V + 'items'][0][V + 'desired'] = '17'
    assert state_from_resources(resources).temperature == 24
    assert command_payload('temperature', 25, resources) == ('/temperature/desired/0', {'temperature': 25})


def test_vendor_temperature_fallback(resources):
    del resources['/temperature/desired/0']
    path, body = command_payload('temperature', 25, resources)
    assert path == '/temperatures/vs/0'
    assert body[V + 'items'] == [{V + 'id': '0', V + 'desired': '25.0'}]


def test_only_changes_requested_field(resources):
    assert command_payload('power', False, resources) == ('/power/vs/0', {V + 'power': 'Off'})
    assert command_payload('mode', 'Dry', resources) == (MODE, {V + 'modes': ['Dry']})
    assert command_payload('fan', '3', resources) == (FAN, {V + 'modes': '3'})


def test_rejects_unadvertised_mode(resources):
    with pytest.raises(ValueError):
        command_payload('mode', 'Heat', resources)


def test_windfree_uses_device_nano_preset(resources):
    assert command_payload('windfree', True, resources) == (PRESET, {V + 'modes': 'Nano'})
    assert command_payload('windfree', False, resources) == (PRESET, {V + 'modes': 'Off'})


def test_windfree_preserves_sleep(resources):
    resources[PRESET][V + 'modes'] = 'Sleep'
    assert command_payload('windfree', True, resources) == (PRESET, {V + 'modes': 'NanoSleep'})


def test_no_windfree_for_unknown_capability():
    assert state_from_resources({}).windfree is None
    with pytest.raises(ValueError):
        command_payload('windfree', True, {})


def test_recursive_collection_does_not_treat_identity_as_resource():
    assert flatten_resources([{'di': 'example'}, {'href': '/device/0', 'rep': {'links': [
        {'href': '/power/vs/0', 'rep': {V + 'power': 'On'}}]}}])['/power/vs/0'] == {V + 'power': 'On'}


@pytest.mark.parametrize('host', ['8.8.8.8', '127.0.0.1', '0.0.0.0', '224.0.0.1', 'samsung.com', '192.168.0.1:80', '::1'])
def test_only_private_ipv4_can_be_targeted(host):
    with pytest.raises(ValueError):
        validate_host(host)


def test_rejects_coap_success_when_value_did_not_change(resources, monkeypatch):
    resources['/power/vs/0'][V + 'power'] = 'On'
    class Session:
        def get(self, path, **kwargs):
            return 69, cbor2.dumps(resources['/'+'/'.join(path)])
        def post(self, *args, **kwargs):
            return 68, b''
    device = Device()
    device.session = Session()
    device.resources = resources
    monkeypatch.setattr('aircon.device.time.sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='não confirmou'):
        device.command('temperature', 25)


def test_returns_confirmed_state(resources, monkeypatch):
    resources['/power/vs/0'][V + 'power'] = 'On'
    class Session:
        def get(self, path, **kwargs):
            return 69, cbor2.dumps(resources['/'+'/'.join(path)])
        def post(self, *args, **kwargs):
            resources['/temperature/desired/0']['temperature'] = 25
            return 68, b''
    device = Device()
    device.session = Session()
    device.resources = resources
    monkeypatch.setattr('aircon.device.time.sleep', lambda _: None)
    assert device.command('temperature', 25).temperature == 25


def test_windfree_in_auto_does_not_silently_change_mode(resources, monkeypatch):
    resources['/power/vs/0'][V + 'power'] = 'On'
    resources[MODE][V + 'modes'] = ['Auto']
    device = Device()
    device.session = object()
    device.resources = resources
    monkeypatch.setattr(device, 'read_resource', lambda *args, **kwargs: state_from_resources(resources))
    with pytest.raises(ValueError, match='Resfriar'):
        device.command('windfree', True)


def test_cannot_adjust_temperature_while_appliance_is_off(resources, monkeypatch):
    device = Device()
    device.session = object()
    device.resources = resources
    monkeypatch.setattr(device, 'read_resource', lambda *args, **kwargs: state_from_resources(resources))
    with pytest.raises(ValueError, match='Ligue o aparelho'):
        device.command('temperature', 25)


def test_nano_preset_uses_same_mode_guard_as_windfree(resources, monkeypatch):
    resources['/power/vs/0'][V + 'power'] = 'On'
    resources[MODE][V + 'modes'] = ['Auto']
    device = Device()
    device.session = object()
    device.resources = resources
    monkeypatch.setattr(device, 'read_resource', lambda *args, **kwargs: state_from_resources(resources))
    with pytest.raises(ValueError, match='Resfriar'):
        device.command('preset', 'Nano')


@pytest.mark.parametrize('peer_id,accepted', [('expected', True), ('other-device', False)])
def test_remembered_endpoint_verifies_identity_over_secure_channel(resources, monkeypatch, peer_id, accepted):
    import cbor2
    class Session:
        def __init__(self, *args, **kwargs):
            self.closed = False
        def connect(self):
            pass
        def start_reader(self):
            pass
        def close(self):
            self.closed = True
        def get(self, path, **kwargs):
            if path == ['oic', 'd']:
                return 69, cbor2.dumps({'rt': ['oic.d.airconditioner'], 'di': peer_id})
            return 69, cbor2.dumps([{'href': href, 'rep': rep} for href, rep in resources.items()])
    monkeypatch.setattr('aircon.device.DtlsCoapSession', Session)
    monkeypatch.setattr('aircon.device.client_identity', lambda: {'cert': 'test', 'key': 'test'})
    monkeypatch.setattr('aircon.device.inspect_host', lambda *args, **kwargs: pytest.fail('Should use the remembered secure port'))
    device = Device()
    if accepted:
        assert device.connect('192.168.1.10', 'expected', 49154)['device_id'] == 'expected'
    else:
        with pytest.raises(ConnectionError, match='outro aparelho'):
            device.connect('192.168.1.10', 'expected', 49154)
        assert device.session is None


@pytest.mark.parametrize('token,lit', [('Light_On', False), ('Light_Off', True)])
def test_display_light_token_has_inverted_polarity(resources, token, lit):
    resources[MODE][V + 'options'] = ['Sleep_4', 'Volume_Mute', token]
    assert state_from_resources(resources).display_light is lit
    assert command_payload('display_light', not lit, resources) == (MODE, {V + 'options': [
        'Light_Off' if not lit else 'Light_On']})
    assert resources[MODE][V + 'options'] == ['Sleep_4', 'Volume_Mute', token]


def test_dedicated_light_uses_normal_polarity():
    resources = {'/light/vs/0': {'mode': 'On'}}
    assert state_from_resources(resources).display_light is True
    assert command_payload('display_light', False, resources) == ('/light/vs/0', {'mode': 'Off'})


def test_light_control_not_offered_without_capability():
    assert state_from_resources({}).display_light is None
    with pytest.raises(ValueError):
        command_payload('display_light', True, {})


def test_light_can_change_while_air_conditioner_is_off(resources, monkeypatch):
    class Session:
        def get(self, path, **kwargs):
            return 69, cbor2.dumps(resources['/'+'/'.join(path)])
        def post(self, path, body, **kwargs):
            import cbor2
            option = cbor2.loads(body)[V + 'options'][0]
            resources[MODE][V + 'options'] = [option]
            return 68, b''
    device = Device()
    device.session = Session()
    device.resources = resources
    monkeypatch.setattr('aircon.device.time.sleep', lambda _: None)
    assert device.command('display_light', True).display_light is True
    assert state_from_resources(resources).power is False


def test_immediate_readback_does_not_wait_or_read_the_full_device(resources, monkeypatch):
    import cbor2
    requests, delays = [], []
    class Session:
        def get(self, path, **kwargs):
            href = '/'+'/'.join(path); requests.append(('GET', href))
            data = [{'href': key, 'rep': value} for key, value in resources.items()] if href == '/device/0' else resources[href]
            return 69, cbor2.dumps(data)
        def post(self, path, body, **kwargs):
            href = '/'+'/'.join(path); requests.append(('POST', href))
            resources[href].update(cbor2.loads(body))
            return 68, b''
    device = Device(); device.session = Session(); device.resources = resources
    monkeypatch.setattr('aircon.device.time.sleep', delays.append)
    assert device.command('display_light', True).display_light is True
    assert delays == []
    assert ('GET', '/device/0') not in requests
    assert requests[0] == ('POST', MODE)


def test_notification_confirms_without_an_extra_get(resources):
    device = Device(); device.resources = resources
    class Session:
        def get(self, *args, **kwargs):
            pytest.fail('A fresh notification already confirmed the command')
        def post(self, path, body, **kwargs):
            rep = {**resources[MODE], **cbor2.loads(body)}
            device._notification(device._generation, MODE, cbor2.dumps(rep))
            return 68, b''
    device.session = Session()
    assert device.command('display_light', True).display_light is True
    assert device.last_timing['source'] == 'notification'


def test_cached_value_and_metadata_only_reply_do_not_confirm(resources, monkeypatch):
    resources[MODE][V+'options'] = ['Light_Off']
    class Session:
        def get(self, *args, **kwargs): return 69, cbor2.dumps({'causeSource': 'test'})
        def post(self, *args, **kwargs): return 68, b''
    device = Device(); device.session = Session(); device.resources = resources
    monkeypatch.setattr('aircon.device.time.sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='não confirmou'):
        device.command('display_light', True)


def test_stale_observe_registration_is_not_a_command_confirmation(resources, monkeypatch):
    class Session:
        def get(self, path, **kwargs): return 69, cbor2.dumps(resources['/'+'/'.join(path)])
        def post(self, *args, **kwargs): return 68, b''
    device = Device(); device.session = Session(); device.resources = resources
    device._notification(device._generation, MODE, cbor2.dumps(resources[MODE]))
    monkeypatch.setattr(device._condition, 'wait_for', lambda predicate, timeout: predicate())
    monkeypatch.setattr(device._condition, 'wait', lambda _: None)
    with pytest.raises(RuntimeError, match='não confirmou'):
        device.command('display_light', True)


def test_fresh_power_read_blocks_command_after_external_power_off(resources):
    resources['/power/vs/0'][V+'power'] = 'On'
    class Session:
        def get(self, path, **kwargs):
            assert path == ['power', 'vs', '0']
            return 69, cbor2.dumps({V+'power': 'Off'})
        def post(self, *args, **kwargs): pytest.fail('Off appliance cannot accept climate changes')
    device = Device(); device.session = Session(); device.resources = resources
    with pytest.raises(ValueError, match='Ligue o aparelho'):
        device.command('temperature', 25)


def test_snapshot_read_does_not_overwrite_a_newer_notification(resources):
    original = copy.deepcopy(resources)
    device = Device(); device.resources = resources
    class Session:
        def get(self, path, **kwargs):
            device._notification(device._generation, MODE, cbor2.dumps({V+'options': ['Light_Off']}))
            return 69, cbor2.dumps([{'href': href, 'rep': rep} for href, rep in original.items()])
    device.session = Session()
    assert device.refresh().display_light is True


def test_background_poll_reads_only_one_resource(resources):
    requests = []
    class Session:
        def get(self, path, **kwargs):
            href = '/'+'/'.join(path); requests.append(href)
            return 69, cbor2.dumps(resources[href])
    device = Device(); device.resources = resources; device.session = Session()
    for _ in range(3): device.poll()
    assert len(requests) == 3 and len(set(requests)) == 3
    assert '/device/0' not in requests


def test_targeted_read_does_not_overwrite_a_newer_notification(resources):
    original = copy.deepcopy(resources[MODE])
    device = Device(); device.resources = resources
    class Session:
        def get(self, path, **kwargs):
            device._notification(device._generation, MODE, cbor2.dumps({V+'options': ['Light_Off']}))
            return 69, cbor2.dumps(original)
    device.session = Session()
    assert device.read_resource(MODE).display_light is True
