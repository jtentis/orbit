import hashlib
import pytest
from app import updater

PAYLOAD = b'new orbit build'


class _Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def raise_for_status(self): pass
    def json(self): return self.data
    def iter_content(self, _): yield self.data


def _release(monkeypatch, tmp_path, tag, digest):
    monkeypatch.setattr(updater, 'BUILD', 5)
    monkeypatch.setattr(updater.sys, 'executable', str(tmp_path / 'Orbit.exe'))
    asset = {'name': 'Orbit.exe', 'size': len(PAYLOAD), 'digest': digest, 'browser_download_url': 'exe'}
    monkeypatch.setattr(updater.requests, 'get', lambda url, **_: _Response(
        PAYLOAD if url == 'exe' else {'tag_name': tag, 'assets': [asset]}))


def test_newer_release_is_staged_after_digest_check(monkeypatch, tmp_path):
    _release(monkeypatch, tmp_path, 'build-6', 'sha256:' + hashlib.sha256(PAYLOAD).hexdigest())
    assert updater.download_update().read_bytes() == PAYLOAD


def test_same_or_older_release_is_ignored(monkeypatch, tmp_path):
    _release(monkeypatch, tmp_path, 'build-5', None)
    assert updater.download_update() is None


def test_corrupted_download_is_discarded(monkeypatch, tmp_path):
    _release(monkeypatch, tmp_path, 'build-6', 'sha256:' + '0' * 64)
    with pytest.raises(ValueError):
        updater.download_update()
    assert not (tmp_path / 'Orbit.new.exe').exists()
