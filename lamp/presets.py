WHITE_PRESETS = (('warm', 'Quente', 3000), ('neutral', 'Neutro', 4000), ('cool', 'Frio', 6500))


def white_preset_value(state, kelvin):
    # Linear estimate: Tuya does not report calibrated kelvin.
    value = round((kelvin-3000)/3500*100) if state.white_unit == '%' else kelvin
    return value if state.minimum_kelvin <= value <= state.maximum_kelvin else None
