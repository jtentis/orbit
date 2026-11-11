from logging.handlers import RotatingFileHandler
import logging
import os
import sys
from shared.storage import DATA_DIR

LOG = logging.getLogger('app.startup')
LOG.setLevel(logging.INFO)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / 'orbit.log', maxBytes=256000, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.WARNING, handlers=[handler], format='%(asctime)s %(levelname)s %(name)s: %(message)s', force=True)
    LOG.info('[startup] stage=begin pid=%s automatic=%s', os.getpid(), '--startup' in sys.argv)
    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from app.tray import TrayApp
    from app.icons import orbit_icon
    app = QApplication(sys.argv)
    app.setFont(QFont('Segoe UI', 10))
    app.setApplicationName('Orbit')
    app.setWindowIcon(orbit_icon())
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(DATA_DIR / 'app.lock'))
    # After a self-update the previous process may still be shutting down.
    if not lock.tryLock(30000 if '--after-update' in sys.argv else 100):
        LOG.info('[startup] stage=already_running')
        return 0
    if not QSystemTrayIcon.isSystemTrayAvailable():
        LOG.warning('[startup] stage=waiting_for_windows_tray')
    try:
        controller = TrayApp(app)
        LOG.info('[startup] stage=ready')
        return app.exec()
    except Exception:
        logging.exception('Falha ao iniciar Orbit')
        return 1
    finally:
        lock.unlock()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        logging.exception('Falha ao carregar dependências do Orbit')
        sys.exit(1)
