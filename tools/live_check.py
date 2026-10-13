"""Reversible write validation on the selected, already-connected appliance."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windfree.device import Device
from windfree.storage import save_config

device = Device()
host = sys.argv[1]
try:
    info = device.connect(host)
    original = device.refresh()
    save_config(info)
    print(f'Conectado: {host}; ligado={original.power}; temperatura={original.temperature}', flush=True)
    # Verify power without starting the compressor or changing the actual power state.
    state = device.command('power', original.power)
    print(f'Comando de energia confirmado: {state.power}', flush=True)
    if original.power:
        target = original.temperature + original.step
        if target > original.maximum:
            target = original.temperature - original.step
        try:
            state = device.command('temperature', target)
            print(f'Temperatura alterada e lida: {state.temperature}', flush=True)
        finally:
            restored = device.command('temperature', original.temperature)
            print(f'Temperatura original restaurada: {restored.temperature}', flush=True)
    else:
        print('Aparelho desligado: ajustes exigem ligar. Use live_check_on.py para o teste completo.', flush=True)
finally:
    device.close()
