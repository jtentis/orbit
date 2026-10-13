"""Read-only live-state smoke test of the real Windows popup and keyboard behavior."""
import sys
import ctypes
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QGuiApplication, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.panel import ControlPanel
from aircon.device import Device
from shared.storage import load_config, load_secret
from lamp.local import discover_local, LocalLamp

config = load_config()
found_lamps = discover_local()
lamp_state = None
lamp_info = config.get('lamp', {})
lamp_secret = load_secret('local-lamp')
if lamp_info.get('provider') == 'local' and lamp_secret and lamp_info.get('device_id') == lamp_secret.get('device_id'):
    lamp = LocalLamp()
    try: lamp_state = lamp.connect(lamp_info, lamp_secret['key'])
    finally: lamp.close()
device = Device()
try:
    device.connect(config['host'], config.get('device_id'), config.get('port'))
    state = device.refresh()
finally:
    device.close()
Path('.research').mkdir(exist_ok=True)
app = QApplication([]); app.setFont(QFont('Segoe UI',10)); app.setQuitOnLastWindowClosed(False)
panel = ControlPanel(); panel.render(state, True, False, 'Estado confirmado', config)
area = QGuiApplication.primaryScreen().availableGeometry()
anchor = QRect(area.right()-35, area.bottom()+1, 24, 24)
panel.toggle_at(anchor)
def inspect():
    panel.grab().save('.research/panel-live-preview.png')
    window_style = ctypes.windll.user32.GetWindowLongW(int(panel.winId()), -16)
    extended_style = ctypes.windll.user32.GetWindowLongW(int(panel.winId()), -20)
    assert window_style & 0x80000000 # WS_POPUP
    assert not extended_style & 0x00040000 # WS_EX_APPWINDOW
    assert area.contains(panel.geometry())
    assert panel.geometry().right() == area.right()
    assert panel.geometry().bottom() == area.bottom()
    panel.show_page(1)
    QTest.qWait(230)
    assert panel.pages.currentIndex()==1
    QTest.keyClick(panel.ip_field, Qt.Key.Key_Escape)
    assert panel.pages.currentIndex()==0
    panel.select_device('lamp'); panel.lamp_local_setup.set_found(found_lamps); panel.show_page(4)
    QTest.qWait(230)
    assert panel.pages.currentIndex() == 4 and panel.devices.isVisible()
    panel.grab().save('.research/lamp-live-setup-preview.png')
    if not lamp_state: assert not panel.lamp_page.power.isEnabled()
    QTest.keyClick(panel.lamp_local_setup.search, Qt.Key.Key_Escape)
    assert panel.pages.currentIndex() == 2
    if lamp_state:
        panel.render_lamp(lamp_state, True, False, 'Wi-Fi local · confirmado pela lâmpada', lamp_info, True, cloud_configured=False)
        QTest.qWait(270)
        assert panel.lamp_page.power.isEnabled()
        assert panel.lamp_page.level.value() == lamp_state.level
        assert panel.lamp_page.kelvin_value.text() == f'{lamp_state.kelvin:g}%'
        panel.grab().save('.research/lamp-live-preview.png')
    panel.select_device('ac')
    QTest.keyClick(panel.power_button, Qt.Key.Key_Escape)
    QTest.qWait(200)
    assert not panel.isVisible()
    assert not panel.appliance.timer.isActive()
    print('Popup Windows: conexão real, posição, ausência de barra de tarefas, Escape e timers OK', flush=True)
    app.quit()
QTimer.singleShot(450, inspect)
QTimer.singleShot(6000, app.quit)
app.exec()
