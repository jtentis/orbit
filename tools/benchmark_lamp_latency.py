"""Measure real local commands; restore exact original lighting DPs on exit."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lamp.local import LocalLamp
from shared.storage import DATA_DIR, load_config, load_secret


def configure_logging():
    logging.basicConfig(level=logging.WARNING,
        handlers=[RotatingFileHandler(DATA_DIR/'orbit.log', maxBytes=256000, backupCount=2, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def snapshot(device):
    return {str(device.bulb.dpset[name]): device.dps[str(device.bulb.dpset[name])]
            for name in ('switch', 'mode', 'brightness', 'colourtemp', 'colour')}


def restore(device, info, key, original):
    device.close(); device.connect(info, key)
    changed = {k: v for k, v in original.items() if device.dps.get(k) != v}
    if changed: device.bulb.set_multiple_values(changed)
    for _ in range(8):
        device.refresh()
        if all(device.dps.get(k) == v for k, v in original.items()): return
        time.sleep(.1)
    raise RuntimeError('Restauração exata não confirmada.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--rounds', type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()
    configure_logging()
    info, secret = load_config()['lamp'], load_secret('local-lamp')
    if secret['device_id'] != info['device_id']: raise RuntimeError('Identidade divergente.')
    report = {'operations': []}
    device = LocalLamp()
    original = None
    try:
        device.connect(info, secret['key'])
        state = device.refresh()
        original = snapshot(device)
        report['original'] = original
        Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
        if state.color_mode not in ('white', 'color'):
            raise RuntimeError('O teste de brilho requer branco ou RGB.')
        if not state.power: state = device.command('power', True)
        trace = []
        started = 0
        def measured(label, method):
            def run(*values, **kwargs):
                begin = time.perf_counter()
                result = method(*values, **kwargs)
                trace.append({'stage': label, 'start_ms': round((begin-started)*1000, 2),
                              'duration_ms': round((time.perf_counter()-begin)*1000, 2)})
                return result
            return run
        device.bulb.status = measured('read', device.bulb.status)
        device.bulb.receive = measured('notification', device.bulb.receive)
        device.bulb.set_multiple_values = measured('write', device.bulb.set_multiple_values)
        target = state.level+5 if state.level <= 95 else state.level-5
        for value in (target, state.level)*args.rounds:
            trace.clear(); started = time.perf_counter()
            result = device.command('level', value)
            assert result.level == value and result.power == state.power and result.color_mode == state.color_mode
            elapsed = round((time.perf_counter()-started)*1000, 2)
            report['operations'].append({'value': value, 'total_ms': elapsed, 'requests': list(trace)})
            print('Brilho', value, '%; confirmação', elapsed, 'ms;', trace, flush=True)
    finally:
        try:
            if original is not None:
                restore(device, info, secret['key'], original)
                report['restored'] = True
                print('Energia, modo, brilho, branco e RGB originais restaurados.', flush=True)
        finally:
            device.close()
            if report['operations']:
                report['median_ms'] = round(statistics.median(x['total_ms'] for x in report['operations']), 2)
                Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
                print('Mediana:', report['median_ms'], 'ms', flush=True)


if __name__ == '__main__': main()
