import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.storage import DATA_DIR, load_config
from windfree.device import Device


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--rounds', type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING,
        handlers=[RotatingFileHandler(DATA_DIR / 'windfree.log', maxBytes=256000, backupCount=2, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.getLogger('benchmark').setLevel(logging.INFO)
    device = Device()
    report = {'operations': []}
    config = load_config()
    original = None
    try:
        start = time.perf_counter()
        device.connect(config['host'], config.get('device_id'), config.get('port'))
        report['connect_ms'] = round((time.perf_counter()-start)*1000, 2)
        original = device.refresh()
        if original.display_light is None:
            raise RuntimeError('O aparelho não informou a luz do display.')
        trace = []
        wire_posts = []
        command_started = 0
        def instrument(method, callback):
            def measured(path, *values, **kwargs):
                started = time.perf_counter()
                result = callback(path, *values, **kwargs)
                trace.append({'method': method, 'path': '/'+ '/'.join(path),
                              'start_ms': round((started-command_started)*1000, 2),
                              'duration_ms': round((time.perf_counter()-started)*1000, 2),
                              'response_bytes': len(result[1] or b'')})
                return result
            return measured
        device.session.get = instrument('GET', device.session.get)
        device.session.post = instrument('POST', device.session.post)
        send = device.session._send_dgram
        def measured_send(datagram):
            if len(datagram) > 1 and datagram[1] == 2:
                elapsed = round((time.perf_counter()-command_started)*1000, 2)
                wire_posts.append(elapsed)
                logging.getLogger('benchmark').info('[latency] stage=wire_post elapsed_ms=%s', elapsed)
            return send(datagram)
        device.session._send_dgram = measured_send
        for _ in range(args.rounds):
            for target in (not original.display_light, original.display_light):
                trace.clear(); wire_posts.clear(); command_started = time.perf_counter()
                updated = device.command('display_light', target)
                duration = round((time.perf_counter()-command_started)*1000, 2)
                assert updated.display_light is target and updated.power == original.power
                post = next(item for item in trace if item['method'] == 'POST')
                report['operations'].append({'kind': 'display_light', 'value': target,
                    'total_ms': duration, 'post_started_ms': post['start_ms'],
                    'wire_attempt_ms': wire_posts[0],
                    'post_ms': post['duration_ms'], 'requests': list(trace)})
                print(f'Luz={target}: início do POST={post["start_ms"]:.0f} ms, POST={post["duration_ms"]:.0f} ms, confirmado={duration:.0f} ms', flush=True)
    finally:
        try:
            if original:
                state = device.refresh()
                if state.display_light != original.display_light:
                    device.command('display_light', original.display_light)
                restored = device.refresh()
                for name in ('power', 'temperature', 'mode', 'fan', 'swing', 'preset', 'display_light'):
                    assert getattr(restored, name) == getattr(original, name), f'Ajuste original não restaurado: {name}'
                report['restored'] = True
                print('Ajustes originais conferidos e preservados.', flush=True)
        finally:
            device.close()
            if report['operations']:
                durations = [item['total_ms'] for item in report['operations']]
                report['median_ms'] = round(statistics.median(durations), 2)
                Path(args.output).write_text(json.dumps(report, indent=2), encoding='utf-8')
                print('Mediana:', report['median_ms'], 'ms', flush=True)


if __name__ == '__main__':
    main()
