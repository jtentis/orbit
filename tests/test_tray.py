from types import SimpleNamespace
from app.tray import TrayApp


def test_queued_notification_uses_latest_device_snapshot():
    latest = object()
    controller = SimpleNamespace(online=True, state=None,
        device=SimpleNamespace(snapshot=lambda: latest), sync_panel=lambda: None)
    TrayApp.observed_state(controller, object())
    assert controller.state is latest


def test_ignored_command_does_not_replace_the_active_timing_id():
    controller = SimpleNamespace(busy=True, operation='command',
        _request_id='active', _command_requested_at=10)
    TrayApp.command(controller, 'display_light', True, requested_at=20, request_id='ignored')
    assert controller._request_id == 'active' and controller._command_requested_at == 10


def test_manual_check_reports_when_there_is_nothing_new():
    from types import SimpleNamespace as N
    from app import updater
    calls = []
    controller = N(manual_check=True, panel=N(set_update_state=lambda *args: calls.append(args)))
    TrayApp.update_finished(controller, 'none', None)
    assert calls == [(f'Build {updater.BUILD} · o mais recente', True)]


def test_automatic_check_stays_silent_faced_with_the_panel():
    from types import SimpleNamespace as N
    calls = []
    controller = N(manual_check=False, panel=N(set_update_state=lambda *args: calls.append(args)))
    TrayApp.update_finished(controller, 'error', None)
    assert calls == []
