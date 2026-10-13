"""Validate a small brightness adjustment, restoring exact original lamp DPs.

Only run when a physical lighting test is desired. Never print the local key.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windfree.storage import load_config, load_secret
from windfree.lamp_local import LocalLamp


def main():
    info = load_config().get('lamp', {})
    secret = load_secret('local-lamp')
    if not secret or info.get('device_id') != secret.get('device_id'):
        raise RuntimeError('A identidade e a credencial local não correspondem.')
    device = LocalLamp()
    try:
        initial = device.connect(info, secret['key'])
        if not initial.power or initial.color_mode != 'white' or 'switchLevel' not in initial.capabilities:
            print('Conexão e leitura locais confirmadas; teste físico de brilho não necessário neste estado.')
            return
        response = device.bulb.status()
        dps = response['dps']; mapping = device.bulb.dpset
        tracked = {str(mapping[feature]): dps[str(mapping[feature])]
                   for feature in ('switch', 'mode', 'brightness', 'colourtemp', 'colour') if mapping.get(feature)}
        target = initial.level+5 if initial.level <= 95 else initial.level-5
        brightness_dp = str(mapping['brightness'])
        try:
            updated = device.command('level', target)
            if abs(updated.level-target) > 1: raise RuntimeError('Brilho não confirmado.')
            print('Brilho confirmado pela lâmpada:', initial.level, '->', updated.level, '%')
        finally:
            device.bulb.set_multiple_values({brightness_dp: tracked[brightness_dp]})
            verified = False
            for delay in (.3, .7, 1.5):
                device.sleep(delay)
                after = device.bulb.status().get('dps', {})
                if all(after.get(dp) == value for dp, value in tracked.items()):
                    verified = True; break
            if not verified: raise RuntimeError('A restauração dos ajustes originais não foi confirmada.')
            print('Brilho original exato restaurado; energia, modo, branco e RGB preservados.')
    finally:
        device.close()


if __name__ == '__main__':
    main()
