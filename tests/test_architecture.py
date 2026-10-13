import subprocess
import sys


def test_lamp_transports_load_without_samsung_or_desktop_ui():
    result = subprocess.run(
        [sys.executable, '-c', '''
import sys
from lamp.local import LocalLamp
from lamp.smartthings import SmartThingsLamp
from lamp.presets import WHITE_PRESETS
assert LocalLamp and SmartThingsLamp and len(WHITE_PRESETS) == 3
assert not any(name.split('.')[0] in {'windfree', 'app', 'PySide6'} for name in sys.modules)
'''],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
