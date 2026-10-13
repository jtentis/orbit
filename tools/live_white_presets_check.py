"""Test white presets on an already-on white lamp, then restore exact native DPs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.storage import load_config, load_secret
from lamp.local import LocalLamp
from lamp.presets import WHITE_PRESETS, white_preset_value


def main():
    info = load_config().get('lamp', {})
    secret = load_secret('local-lamp')
    if not secret or info.get('device_id') != secret.get('device_id'):
        raise RuntimeError('A identidade e a credencial local não correspondem.')
    device = LocalLamp()
    try:
        initial = device.connect(info, secret['key'])
        if not initial.power or initial.color_mode != 'white':
            print('Leitura local confirmada; teste físico requer lâmpada já ligada em branco.')
            return
        mapping = device.bulb.dpset
        tracked = {str(mapping[feature]): device.dps[str(mapping[feature])]
                   for feature in ('switch', 'mode', 'brightness', 'colourtemp', 'colour')}
        white_dp = str(mapping['colourtemp'])
        try:
            for _, caption, kelvin in WHITE_PRESETS:
                target = white_preset_value(initial, kelvin)
                updated = device.command('kelvin', target)
                assert updated.color_mode == 'white' and updated.kelvin == target
                assert all(device.dps.get(dp) == value for dp, value in tracked.items() if dp != white_dp)
                print('Branco confirmado:', caption, '· escala local:', target, '%', flush=True)
        finally:
            device.bulb.set_multiple_values({white_dp: tracked[white_dp]})
            verified = False
            for delay in (.3, .7, 1.5):
                device.sleep(delay); device.refresh()
                if all(device.dps.get(dp) == value for dp, value in tracked.items()):
                    verified = True; break
            if not verified: raise RuntimeError('A restauração dos ajustes originais não foi confirmada.')
            print('Branco original exato restaurado; energia, brilho e RGB preservados.')
    finally:
        device.close()


if __name__ == '__main__':
    main()
