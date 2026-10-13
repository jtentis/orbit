"""Capture the actual popup without connecting its commands to hardware."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtTest import QTest
from windfree.ui import ControlPanel
from windfree.device import state_from_resources

app = QApplication([])
for font in ['segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
app.setFont(QFont('Segoe UI', 10)); app.setStyle('Fusion')
state = state_from_resources(json.loads(Path('tests/fixtures/ar12-controls.json').read_text()))
state.power = True; state.display_light = True
panel = ControlPanel()
panel.resize(388, 650)
config = {'host': '192.168.15.13', 'reduce_motion': True}
panel.render(state, True, False, 'Estado confirmado', config)
panel.show(); app.processEvents(); QTest.qWait(80)
Path('assets').mkdir(exist_ok=True)
panel.grab().save('assets/panel-preview.png')
print('Altura do conteúdo:', panel.content.sizeHint().height(), 'rolagem:', panel.scroll.verticalScrollBar().maximum())
panel.show_page(1); app.processEvents(); panel.grab().save('assets/settings-preview.png')
panel.show_page(0); state.power = False
panel.render(state, True, False, 'Estado confirmado', config)
app.processEvents(); panel.grab().save('assets/panel-off-preview.png')
panel.hide()
