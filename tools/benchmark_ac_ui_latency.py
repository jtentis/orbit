import json
import logging
from logging.handlers import RotatingFileHandler
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.tray import TrayApp
from shared.storage import DATA_DIR


def main():
    logging.basicConfig(level=logging.WARNING,
        handlers=[RotatingFileHandler(DATA_DIR / 'windfree.log', maxBytes=256000, backupCount=2, encoding='utf-8')],
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    app = QApplication([]); app.setFont(QFont('Segoe UI', 10)); app.setQuitOnLastWindowClosed(False)
    controller = TrayApp(app)
    report = []; original = None; target = None; requested = 0; confirmed = None
    deadline = time.perf_counter()+30; error = []
    timer = QTimer(); timer.setInterval(5)
    def finish():
        timer.stop()
        try:
            if original is not None:
                future = controller.executor.submit(controller.device.command, 'display_light', original)
                assert future.result(timeout=10).display_light == original
            Path('.research/latency-ui.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            if report:
                print('Mediana clique -> leitura confirmada na UI:', round(statistics.median(item['confirmed_ms'] for item in report)), 'ms', flush=True)
        except Exception as failure:
            error.append(type(failure).__name__)
        app.quit()
    def step():
        nonlocal original, target, requested, confirmed
        if time.perf_counter() > deadline:
            error.append('timeout'); finish(); return
        if not controller.online or not controller.state:
            return
        if original is None:
            original = controller.state.display_light
            controller.panel.toggle_at(controller.tray.geometry())
        if target is not None:
            elapsed = (time.perf_counter()-requested)*1000
            if controller.panel.light_toggle.isChecked() == target and confirmed is None:
                confirmed = elapsed
            if confirmed is not None and not controller.busy and abs(controller.panel.light_toggle.position-float(target)) < .001:
                report.append({'confirmed_ms': round(confirmed, 2), 'visual_complete_ms': round(elapsed, 2)})
                print('Clique -> confirmação:', round(confirmed), 'ms; animação concluída:', round(elapsed), 'ms', flush=True)
                target = None
                if len(report) == 6:
                    finish(); return
        if target is None and not controller.busy and controller.panel.light_toggle.isEnabled():
            target = not controller.state.display_light
            requested = time.perf_counter(); confirmed = None
            QTest.mouseClick(controller.panel.light_toggle, Qt.MouseButton.LeftButton)
    timer.timeout.connect(step); timer.start()
    app.exec()
    if error: raise RuntimeError('Teste de UI não concluído: '+str(error))
    print('Preferência original da luz restaurada.', flush=True)


if __name__ == '__main__':
    main()
