"""Self-update of the frozen executable from the latest GitHub release."""
from __future__ import annotations
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import sys
import requests
from .version import BUILD

LATEST = 'https://api.github.com/repos/jtentis/orbit/releases/latest'
ASSET = 'Orbit.exe'
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)


def enabled() -> bool:
    return getattr(sys, 'frozen', False) and BUILD > 0


def _paths():
    current = Path(sys.executable)
    return current, current.with_name('Orbit.new.exe'), current.with_name('Orbit.old.exe')


def download_update() -> Path | None:
    """Stage the latest release next to the executable when it is newer than this build."""
    current, staged, old = _paths()
    try: old.unlink(missing_ok=True)  # left by the previous update; locked while that process exits
    except OSError: pass
    response = requests.get(LATEST, timeout=15, headers={'Accept': 'application/vnd.github+json'})
    response.raise_for_status()
    release = response.json()
    build = int(release['tag_name'].removeprefix('build-'))
    if build <= BUILD: return None
    asset = next(item for item in release['assets'] if item['name'] == ASSET)
    digest = hashlib.sha256()
    with requests.get(asset['browser_download_url'], stream=True, timeout=60) as download, staged.open('wb') as file:
        download.raise_for_status()
        for chunk in download.iter_content(1 << 20):
            digest.update(chunk); file.write(chunk)
    expected = asset.get('digest')
    if staged.stat().st_size != asset['size'] or (expected and expected != 'sha256:' + digest.hexdigest()):
        staged.unlink()
        raise ValueError(f'Download do build {build} não confere com a release.')
    LOG.info('[update] stage=downloaded build=%s current=%s', build, BUILD)
    return staged


def install(staged: Path) -> None:
    """Swap the executables and launch the new one; the caller must quit right after."""
    current, _, old = _paths()
    old.unlink(missing_ok=True)
    current.rename(old)  # Windows allows renaming a running executable, not overwriting it
    try: staged.rename(current)
    except OSError:
        old.rename(current); raise
    # Without the reset, a onefile child would reuse this process's unpacked runtime.
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    subprocess.Popen([str(current), '--after-update'], env=environment, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS)
    LOG.info('[update] stage=installed')
