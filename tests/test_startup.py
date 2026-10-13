import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtCore import QTimer, QLockFile
import main
import importlib
import logging


def test_startup_stays_alive_until_windows_tray_appears(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(main, 'RotatingFileHandler', lambda *args, **kwargs: logging.NullHandler())
    monkeypatch.setattr(main.logging, 'basicConfig', lambda **kwargs: None)
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    monkeypatch.setattr(QLockFile, 'tryLock', lambda *_: True)
    monkeypatch.setattr(QLockFile, 'unlock', lambda *_: None)
    tray_module = importlib.import_module('app.tray')
    started = []
    def controller(application):
        started.append(True); QTimer.singleShot(0, application.quit)
    monkeypatch.setattr(tray_module, 'TrayApp', controller)
    monkeypatch.setattr('PySide6.QtWidgets.QApplication', lambda _: app)
    assert main.main() == 0 and started == [True]
