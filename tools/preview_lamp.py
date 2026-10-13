"""Capture real Qt lamp widgets with sample state, without any account/device IO."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from app.panel import ControlPanel
from lamp.state import LampState

app = QApplication([]); app.setFont(QFont('Segoe UI', 10)); app.setStyle('Fusion')
for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
panel = ControlPanel(); panel.resize(388, 650)
panel.render(None, False, False, 'Sem leitura', {'reduce_motion': True})
panel.select_device('lamp'); panel.show(); app.processEvents()
panel.grab().save('assets/lamp-setup-empty-preview.png')
state = LampState(power=True, level=68, kelvin=29, hue=60, saturation=85,
                  minimum_kelvin=0, maximum_kelvin=100, color_mode='white', white_unit='%', health='ONLINE',
                  capabilities=frozenset({'switch', 'switchLevel', 'colorTemperature', 'colorControl'}))
info = {'provider': 'local', 'device_id': 'demolamp01', 'host': '192.168.1.21', 'version': 3.5, 'name': 'Lâmpada'}
panel.render_lamp(state, True, False, 'Wi-Fi local · confirmado pela lâmpada', info, True)
app.processEvents(); QTest.qWait(80); panel.grab().save('assets/lamp-preview.png')
print('Lamp sample: content height', panel.content.sizeHint().height(), 'scroll', panel.scroll.verticalScrollBar().maximum())
panel.show_page(3); app.processEvents(); panel.grab().save('assets/lamp-account-preview.png')
panel.show_page(4); app.processEvents(); panel.grab().save('assets/lamp-settings-preview.png')
panel.lamp_local_setup.edit(); app.processEvents(); panel.grab().save('assets/lamp-local-setup-preview.png')
panel.hide()
