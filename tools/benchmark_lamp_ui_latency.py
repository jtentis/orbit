"""Measure actual slider release through the worker to confirmed Qt rendering."""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer, Qt, QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider
from app.panel import ControlPanel
from lamp.controller import LampController
from shared.storage import load_config, load_secret
from benchmark_lamp_latency import configure_logging, snapshot, restore


def main():
    configure_logging()
    app = QApplication([]); app.setQuitOnLastWindowClosed(False)
    panel = ControlPanel(); controller = LampController(load_config())
    controller.timer.stop()
    def render():
        panel.render_lamp(controller.state, controller.online, controller.busy,
                          controller.message, controller.info, controller.configured,
                          controller.error, controller.operation)
    controller.changed.connect(render)
    panel.lamp_page.commandRequested.connect(controller.command)
    app.aboutToQuit.connect(controller.shutdown)
    original = None; baseline = None; target = None; requested = 0
    report = []; failures = []; deadline = time.perf_counter()+30
    timer = QTimer(); timer.setInterval(5)
    def finish():
        timer.stop()
        try:
            if original:
                secret = load_secret('local-lamp')
                assert secret['device_id'] == controller.info['device_id']
                controller.executor.submit(restore, controller.local, controller.info,
                                           secret['key'], original).result(timeout=15)
                print('Estado original exato restaurado.', flush=True)
        except Exception as failure: failures.append(type(failure).__name__)
        Path('.research/lamp-ui.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if report:
            print('Mediana soltura -> confirmação na UI:', round(statistics.median(x['confirmed_ms'] for x in report), 2), 'ms', flush=True)
        app.quit()
    def step():
        nonlocal original, baseline, target, requested
        if time.perf_counter() > deadline or controller.error:
            failures.append('timeout' if not controller.error else controller.message); finish(); return
        if not controller.online or controller.busy: return
        if original is None:
            original = snapshot(controller.local); baseline = controller.state.level
            Path('.research/lamp-ui-original.json').write_text(json.dumps(original), encoding='utf-8')
            panel.select_device('lamp'); panel.toggle_at(QRect())
            if not controller.state.power:
                controller.command('power', True); return
        if target is not None:
            if controller.state.level != target or panel.lamp_page.level_value.text() != f'{target}%': return
            elapsed = round((time.perf_counter()-requested)*1000, 2)
            report.append({'target': target, 'confirmed_ms': elapsed})
            print('Soltura -> confirmação na interface:', elapsed, 'ms', flush=True)
            target = None
            if len(report) == 6: finish(); return
        slider = panel.lamp_page.level
        if not slider.isEnabled(): return
        target = baseline if controller.state.level != baseline else baseline+5 if baseline <= 95 else baseline-5
        option = QStyleOptionSlider(); slider.initStyleOption(option)
        handle = slider.style().subControlRect(QStyle.ComplexControl.CC_Slider, option,
                                               QStyle.SubControl.SC_SliderHandle, slider)
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=handle.center())
        slider.setValue(target)
        requested = time.perf_counter()
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=handle.center())
    timer.timeout.connect(step); timer.start(); app.exec()
    if failures: raise RuntimeError('Teste de interface não concluído: '+str(failures))


if __name__ == '__main__': main()
