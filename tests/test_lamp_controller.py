import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import pytest
from PySide6.QtWidgets import QApplication
from lamp.state import LampState
from lamp.smartthings import AuthorizationError
from lamp.local import LocalLamp
from lamp.controller import LampController


@pytest.fixture
def controller():
    app = QApplication.instance() or QApplication([])
    ctrl = LampController({}); ctrl.start_timer.stop(); ctrl.timer.stop()
    yield ctrl
    ctrl.shutdown(); ctrl.deleteLater(); app.processEvents()


def test_local_scan_is_the_default_when_no_credentials_exist(controller, monkeypatch):
    monkeypatch.setattr('lamp.controller.load_secret', lambda _: None)
    operations = []; monkeypatch.setattr(controller, 'submit', lambda operation, work: operations.append(operation))
    controller.start()
    assert operations == ['discover_local']


def test_commands_queued_during_read_are_coalesced(controller, monkeypatch):
    controller.busy = True; controller.operation = 'refresh'; controller.online = True
    controller.command('level', 60); controller.command('level', 80)
    assert controller.queue == {'level': 80}
    operations = []; monkeypatch.setattr(controller, 'submit', lambda operation, work: operations.append(operation))
    controller.finished('refresh', LampState(power=True, health='ONLINE'), None)
    assert operations == ['command'] and controller.queue == {}


def test_expired_cloud_token_does_not_stop_active_local_lamp(controller):
    controller.device = controller.local; controller.online = True; controller.configured = True
    controller.finished('discover', None, AuthorizationError('Token expirado.'))
    assert controller.online and not controller.auth_failed


def test_failed_authentication_never_saves_new_token(controller, monkeypatch):
    saved = []; monkeypatch.setattr('lamp.controller.save_secret', lambda *args: saved.append(args))
    controller.cloud.authorize('old-fixture-token')
    def fail(): raise AuthorizationError('Token inválido.')
    monkeypatch.setattr(controller.cloud, 'discover', fail)
    work_items = []; monkeypatch.setattr(controller, 'submit', lambda operation, work: work_items.append(work))
    controller.authorize('new-fixture-token')
    with pytest.raises(AuthorizationError): work_items[0]()
    assert controller.cloud.token == 'old-fixture-token' and saved == []


def test_three_local_read_failures_trigger_identity_based_rediscovery(controller, monkeypatch):
    controller.device = controller.local; controller.online = True; controller.configured = True
    attempts = []; monkeypatch.setattr(controller, 'reconnect_local', lambda: attempts.append('reconnect'))
    for _ in range(3): controller.finished('refresh', None, RuntimeError('Sem resposta.'))
    assert attempts == ['reconnect']


@pytest.mark.parametrize('failure', [RuntimeError('Wi-Fi ainda indisponível'), ValueError('Recursos ainda não informados')])
def test_saved_lamp_retries_after_first_connection_failure(controller, monkeypatch, failure):
    info = {'provider': 'local', 'device_id': 'fixture01', 'host': '192.168.1.2', 'version': 3.5}
    controller.config['lamp'] = info
    monkeypatch.setattr('lamp.controller.load_secret', lambda _: {'device_id': 'fixture01', 'key': 'fixturelocalkey1'})
    operations = []; monkeypatch.setattr(controller, 'submit', lambda operation, work: operations.append(operation))
    controller.start()
    controller.finished('connect', None, failure)
    assert controller.configured and controller.device is controller.local
    assert controller.retry_timer.isActive()


def test_rediscovery_after_failed_start_preserves_key_and_updates_address(controller, monkeypatch):
    info = {'provider': 'local', 'device_id': 'fixture01', 'host': '192.168.1.2', 'version': 3.5, 'name': 'Meu quarto'}
    controller.config['lamp'] = info
    monkeypatch.setattr('lamp.controller.load_secret', lambda _: {'device_id': 'fixture01', 'key': 'fixturelocalkey1'})
    works = []; monkeypatch.setattr(controller, 'submit', lambda operation, work: works.append(work))
    controller.start()
    monkeypatch.setattr('lamp.controller.discover_local', lambda identity: [{**info, 'host': '192.168.1.8'}])
    calls = []
    def connect(found, key):
        calls.append((found, key)); return LampState(power=False, health='ONLINE')
    monkeypatch.setattr(controller.local, 'connect', connect)
    controller.reconnect_local(); found, state = works[-1]()
    assert calls[-1][1] == 'fixturelocalkey1'
    assert found['host'] == '192.168.1.8' and found['name'] == 'Meu quarto'


def test_successful_retry_stops_retry_timer(controller, monkeypatch):
    info = {'provider': 'local', 'device_id': 'fixture01'}
    monkeypatch.setattr('lamp.controller.save_config', lambda _: None)
    controller.retry_timer.start(1000)
    controller.finished('connect', (info, LampState(power=False, health='ONLINE')), None)
    assert not controller.retry_timer.isActive() and controller.online


def test_local_session_is_released_once_the_lamp_is_idle(controller):
    controller.device = controller.local; controller.online = True; controller.configured = True
    controller.finished('refresh', LampState(power=True, health='ONLINE'), None)
    assert controller.idle_timer.isActive()
    controller.idle_timer.stop()


def test_failed_local_read_frees_the_session_immediately(controller, monkeypatch):
    submitted = []
    controller.device = controller.local
    monkeypatch.setattr(controller.executor, 'submit', lambda work: submitted.append(work))
    controller.finished('refresh', None, RuntimeError('Lâmpada sem resposta local.'))
    assert not controller.idle_timer.isActive() and len(submitted) == 1
