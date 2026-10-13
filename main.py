from logging.handlers import RotatingFileHandler
import logging
import os
import sys
from shared.storage import DATA_DIR

LOG = logging.getLogger('app.startup')
LOG.setLevel(logging.INFO)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / 'windfree.log', maxBytes=256000, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.WARNING, handlers=[handler], format='%(asctime)s %(levelname)s %(name)s: %(message)s', force=True)
    LOG.info('[startup] stage=begin pid=%s automatic=%s', os.getpid(), '--startup' in sys.argv)
    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from app.tray import TrayApp
    from app.icons import orbit_icon
    app = QApplication(sys.argv)
    app.setFont(QFont('Segoe UI', 10))
    app.setApplicationName('WindFree Tray')
    app.setWindowIcon(orbit_icon())
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(DATA_DIR / 'app.lock'))
    if not lock.tryLock(100):
        LOG.info('[startup] stage=already_running')
        return 0
    if not QSystemTrayIcon.isSystemTrayAvailable():
        LOG.warning('[startup] stage=waiting_for_windows_tray')
    try:
        controller = TrayApp(app)
        LOG.info('[startup] stage=ready')
        return app.exec()
    except Exception:
        logging.exception('Falha ao iniciar WindFree Tray')
        return 1
    finally:
        lock.unlock()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        logging.exception('Falha ao carregar dependências do WindFree Tray')
        sys.exit(1)
