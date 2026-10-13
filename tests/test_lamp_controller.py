import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import pytest
from PySide6.QtWidgets import QApplication
from windfree.lamp import LampState, AuthorizationError
from windfree.lamp_local import LocalLamp
from windfree.lamp_controller import LampController


@pytest.fixture
def controller():
    app = QApplication.instance() or QApplication([])
    ctrl = LampController({}); ctrl.start_timer.stop(); ctrl.timer.stop()
    yield ctrl
    ctrl.shutdown(); ctrl.deleteLater(); app.processEvents()


def test_local_scan_is_the_default_when_no_credentials_exist(controller, monkeypatch):
    monkeypatch.setattr('windfree.lamp_controller.load_secret', lambda _: None)
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
    saved = []; monkeypatch.setattr('windfree.lamp_controller.save_secret', lambda *args: saved.append(args))
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
