"""Exercise physical power, white, RGB and brightness with exact restoration."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lamp.local import LocalLamp
from lamp.state import matches
from shared.storage import load_config, load_secret
from benchmark_lamp_latency import configure_logging, snapshot, restore


def main():
    configure_logging()
    info, secret = load_config()['lamp'], load_secret('local-lamp')
    assert info['device_id'] == secret['device_id']
    device = LocalLamp(); original = None; report = []
    try:
        state = device.connect(info, secret['key']); original = snapshot(device)
        Path('.research/lamp-controls-original.json').write_text(json.dumps(original), encoding='utf-8')
        commands = [('power', True), ('kelvin', 0), ('kelvin', 29), ('kelvin', 100),
                    ('color', {'hue': 25, 'saturation': 50}), ('level', min(100, state.level+5)),
                    ('kelvin', 29), ('power', False)]
        for kind, value in commands:
            started = time.perf_counter(); updated = device.command(kind, value)
            assert matches(updated, kind, value)
            duration = round((time.perf_counter()-started)*1000, 2)
            report.append({'kind': kind, 'value': value, 'confirmed_ms': duration})
            print('Confirmado:', kind, value, duration, 'ms', flush=True)
    finally:
        try:
            if original:
                restore(device, info, secret['key'], original)
                print('Todos os DPs originais restaurados, inclusive energia.', flush=True)
        finally:
            device.close()
            Path('.research/lamp-controls.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
