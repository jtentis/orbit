from __future__ import annotations
from dataclasses import dataclass, field
import math


@dataclass
class LampState:
    """Hue, saturation and brightness use percent; white uses white_unit."""
    power: bool | None = None
    level: int | None = None
    kelvin: int | None = None
    hue: float | None = None
    saturation: float | None = None
    minimum_level: int = 1
    maximum_level: int = 100
    minimum_kelvin: int = 2000
    maximum_kelvin: int = 6500
    capabilities: frozenset = field(default_factory=frozenset)
    color_mode: str | None = None
    white_timestamp: str | None = None
    color_timestamps: tuple = ()
    health: str = 'UNKNOWN'
    white_unit: str = 'K'


def command_payload(kind, value, state, component):
    if kind == 'power':
        if not isinstance(value, bool): raise ValueError('Estado de energia inválido.')
        cap, command, args = 'switch', 'on' if value else 'off', []
    elif kind in ('level', 'kelvin'):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
            raise ValueError('Informe um ajuste inteiro válido.')
        cap, command = ('switchLevel', 'setLevel') if kind == 'level' else ('colorTemperature', 'setColorTemperature')
        limits = (state.minimum_level, state.maximum_level) if kind == 'level' else (state.minimum_kelvin, state.maximum_kelvin)
        if not limits[0] <= value <= limits[1]: raise ValueError('Ajuste fora dos limites da lâmpada.')
        args = [int(value)]
    elif kind == 'color':
        if not isinstance(value, dict) or set(value) != {'hue', 'saturation'}:
            raise ValueError('Cor inválida.')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100 for v in value.values()):
            raise ValueError('Cor fora dos limites da lâmpada.')
        cap, command, args = 'colorControl', 'setColor', [dict(value)]
    else:
        raise ValueError('Controle de iluminação desconhecido.')
    if cap not in state.capabilities: raise ValueError('Este controle não está disponível nesta lâmpada.')
    if kind != 'power' and state.power is not True:
        raise ValueError('Ligue a lâmpada antes de ajustar a iluminação.')
    return {'commands': [{'component': component, 'capability': cap, 'command': command, 'arguments': args}]}


def matches(state, kind, value):
    if kind == 'power': return state.power is value
    if kind == 'level': return state.level is not None and abs(state.level-value) <= 1
    if kind == 'kelvin': return state.kelvin is not None and abs(state.kelvin-value) <= (1 if state.white_unit == '%' else 50)
    if kind == 'color':
        if state.hue is None or state.saturation is None: return False
        delta = abs(state.hue-value['hue'])
        return min(delta, 100-delta) <= 1 and abs(state.saturation-value['saturation']) <= 1
    return False


def confirmed_change(before, after, kind, value):
    if not matches(after, kind, value): return False
    if kind not in ('kelvin', 'color'): return True
    modes = ('white', 'colorTemperature') if kind == 'kelvin' else ('color', 'rgb', 'hue')
    if after.color_mode:
        return after.color_mode in modes
    if not matches(before, kind, value): return True
# RGB and white values may remain cached after a mode change.
    if kind == 'kelvin':
        return bool(after.white_timestamp and after.white_timestamp != before.white_timestamp)
    return any(new and new != old for old, new in zip(before.color_timestamps, after.color_timestamps))
