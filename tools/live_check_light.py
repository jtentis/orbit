"""Validate the display-light command and restore the user's original light setting."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aircon.device import Device, MODE, V
from shared.storage import load_config

device = Device()
config = load_config()
try:
    device.connect(config['host'], config.get('device_id'), config.get('port'))
    original = device.refresh()
    if original.display_light is None:
        raise RuntimeError('O aparelho não anunciou um controle de luz.')
    stable_options = ('Sleep_', 'Volume_', 'Autoclean_')
    before_options = [o for o in device.resources[MODE].get(V + 'options', []) if o.startswith(stable_options)]
    print(f'Estado original: luz={original.display_light}, energia={original.power}', flush=True)
    try:
        state = device.command('display_light', not original.display_light)
        print(f'Comando confirmado: luz={state.display_light}, energia={state.power}', flush=True)
        assert state.power == original.power
        assert [o for o in device.resources[MODE].get(V + 'options', []) if o.startswith(stable_options)] == before_options
    finally:
        restored = device.command('display_light', original.display_light)
        print(f'Estado restaurado: luz={restored.display_light}, energia={restored.power}', flush=True)
finally:
    device.close()
