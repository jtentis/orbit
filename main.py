from logging.handlers import RotatingFileHandler
import logging
import sys
from windfree.storage import DATA_DIR


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA_DIR / 'windfree.log', maxBytes=256000, backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.WARNING, handlers=[handler], format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from windfree.tray import TrayApp
    app = QApplication(sys.argv)
    app.setFont(QFont('Segoe UI', 10))
    app.setApplicationName('WindFree Tray')
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(DATA_DIR / 'app.lock'))
    if not lock.tryLock(100):
        return 0
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logging.error('A bandeja do Windows não está disponível nesta sessão.')
        return 1
    try:
        controller = TrayApp(app)
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
