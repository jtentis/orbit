import json
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.storage import DATA_DIR, load_config
from windfree.device import Device


def main():
    logging.basicConfig(level=logging.WARNING,
        handlers=[RotatingFileHandler(DATA_DIR / 'windfree.log', maxBytes=256000, backupCount=2, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    config = load_config(); device = Device(); original = None; report = []
    def run(kind, value, restoring=False):
        started = time.perf_counter()
        state = device.command(kind, value)
        row = {**device.last_timing, 'restoring': restoring,
               'measured_ms': round((time.perf_counter()-started)*1000, 2)}
        report.append(row)
        print(('Restaurado' if restoring else 'Confirmado'), kind, value,
              round(row['measured_ms']), 'ms', 'via', row['source'], flush=True)
        return state
    try:
        device.connect(config['host'], config.get('device_id'), config.get('port'))
        original = device.snapshot()
        if not original.power:
            run('power', True)
        if original.temperature is not None:
            target = original.temperature+original.step if original.temperature+original.step <= original.maximum else original.temperature-original.step
            run('temperature', target)
        if original.fans:
            run('fan', next(code for code, _ in original.fans if code != original.fan))
        if original.windfree is not None:
            if device.snapshot().mode not in ('Cool', 'Dry'):
                run('mode', 'Cool')
            run('windfree', not original.windfree)
        if len(original.swings) > 1:
            run('swing', next(code for code in original.swings if code != original.swing))
    finally:
        try:
            if original:
                errors = []
                for kind in ('mode', 'preset', 'fan', 'swing', 'temperature', 'display_light', 'power'):
                    value = getattr(original, kind)
                    if value is not None and getattr(device.snapshot(), kind) != value:
                        try: run(kind, value, restoring=True)
                        except Exception as error: errors.append((kind, type(error).__name__))
                state = device.refresh()
                for kind in ('power', 'temperature', 'mode', 'preset', 'fan', 'swing', 'windfree', 'display_light'):
                    if getattr(state, kind) != getattr(original, kind): errors.append((kind, 'not_restored'))
                if errors: raise RuntimeError('Restauração não confirmada: '+str(errors))
                print('Todos os ajustes originais restaurados e conferidos.', flush=True)
        finally:
            device.close()
            Path('.research/latency-controls.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
