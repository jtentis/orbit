from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
import pytest
from app import autostart


@pytest.fixture(autouse=True)
def clear_status(monkeypatch):
    monkeypatch.setattr(autostart, '_enabled_cache', None)


def task(enabled=True):
    return ET.fromstring(f'<Task xmlns="{autostart.NS}"><Settings><Enabled>{str(enabled).lower()}</Enabled></Settings></Task>')


def test_repeated_ui_reads_never_spawn_repeated_scheduler_processes(monkeypatch):
    calls = []
    monkeypatch.setattr(autostart, '_query_task', lambda: calls.append(True) or task())
    assert all(autostart.enabled() for _ in range(20))
    assert calls == [True]


def test_windows_disabled_task_takes_precedence_over_legacy_entry(monkeypatch):
    monkeypatch.setattr(autostart, '_query_task', lambda: task(False))
    monkeypatch.setattr(autostart, '_legacy_enabled', lambda: True)
    assert not autostart.enabled()
    monkeypatch.setattr(autostart, 'set_enabled', lambda _: pytest.fail('must preserve disabled startup'))
    autostart.ensure_current()


def test_failed_registration_preserves_existing_startup(monkeypatch):
    monkeypatch.setattr(autostart, '_run_task', lambda *args: SimpleNamespace(returncode=1))
    monkeypatch.setattr(autostart, '_remove_legacy', lambda: pytest.fail('must preserve existing entry'))
    with pytest.raises(RuntimeError): autostart.set_enabled(True)
    assert autostart._enabled_cache is None


def test_registration_handles_spaces_and_xml_characters_in_path(monkeypatch):
    target = r'D:\My app & controls\Orbit.exe'
    monkeypatch.setattr(autostart, '_command', lambda: ([target, '--startup'], Path(target).parent))
    captured = []
    def register(*args):
        captured.append(ET.fromstring(Path(args[args.index('/XML')+1]).read_bytes()))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(autostart, '_run_task', register)
    removed = []; monkeypatch.setattr(autostart, '_remove_legacy', lambda: removed.append(True))
    autostart.set_enabled(True)
    assert captured[0].findtext(f'.//{{{autostart.NS}}}Command') == target
    assert captured[0].findtext(f'.//{{{autostart.NS}}}Arguments') == '--startup'
    assert removed == [True] and autostart.enabled()


def test_disabling_removes_both_owned_startup_entries(monkeypatch):
    monkeypatch.setattr(autostart, '_query_task', lambda: task())
    calls = []; monkeypatch.setattr(autostart, '_run_task', lambda *args: calls.append(args) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(autostart, '_remove_legacy', lambda: calls.append('legacy'))
    autostart.set_enabled(False)
    assert calls == [('/Delete', '/TN', autostart.TASK_NAME, '/F'), 'legacy']
    assert not autostart.enabled()
