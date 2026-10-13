"""Record motion in the actual Qt widgets using isolated sample state, with no hardware connection."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import sys
import subprocess
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import imageio_ffmpeg
import windfree.ui as ui
from windfree.device import state_from_resources

app = QApplication([])
for name in ['segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf']:
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
app.setFont(QFont('Segoe UI', 10)); app.setStyle('Fusion')
# Only this demo ignores the host preference, so exported motion can be inspected.
ui.windows_motion_enabled = lambda: True
panel = ui.ControlPanel(); panel.resize(388,650)
state = state_from_resources(json.loads(Path('tests/fixtures/ar12-controls.json').read_text()))
state.power = True; state.display_light = True
config = {'host': '192.168.15.13'}
panel.render(state, True, False, 'Estado confirmado', config)
panel.show(); app.processEvents()
with tempfile.TemporaryDirectory(prefix='windfree-motion-') as directory:
    folder = Path(directory)
    for frame in range(240):
        if frame == 25:
            panel.slider.setValue(9)
        if frame == 40:
            panel.render(state, True, True, 'Enviando', config, operation='command')
        if frame == 65:
            state.temperature = 25; panel.render(state, True, False, 'Estado confirmado', config)
        if frame == 85:
            panel.render(state, True, True, 'Enviando', config, operation='command')
        if frame == 105:
            state.windfree = True; state.preset = 'Nano'; panel.render(state, True, False, 'Estado confirmado', config)
        if frame == 125:
            state.display_light = False; panel.render(state, True, False, 'Estado confirmado', config)
        if frame == 145:
            state.power = False; panel.render(state, True, False, 'Estado confirmado', config)
        if frame == 175:
            panel.show_page(1)
        if frame == 205:
            panel.show_page(0)
        QTest.qWait(33)
        panel.grab().save(str(folder/f'frame-{frame:03d}.png'))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-framerate', '30', '-i', str(folder/'frame-%03d.png'), '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-crf', '19', '-movflags', '+faststart',
                    'assets/panel-motion-preview.mp4'], check=True)
panel.hide()
print('Motion preview: assets/panel-motion-preview.mp4')
