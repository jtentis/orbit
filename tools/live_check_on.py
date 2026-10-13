import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aircon.device import Device

device = Device()
original = None
try:
    device.connect(sys.argv[1])
    original = device.refresh()
    for kind, value in [('power', True), ('temperature', 25), ('fan', '2'), ('windfree', True)]:
        print('Testando', kind, value, flush=True)
        state = device.command(kind, value)
        print('Confirmado', kind, getattr(state, kind), flush=True)
finally:
    if original:
        for kind, value in [('preset', original.preset), ('fan', original.fan), ('temperature', original.temperature), ('power', original.power)]:
            print('Restaurando', kind, value, flush=True)
            try:
                state = device.command(kind, value)
                print('Restaurado', kind, getattr(state, kind), flush=True)
            except Exception as error:
                print('Falha ao restaurar', kind, str(error), flush=True)
    device.close()
