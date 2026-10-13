import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import sys
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app.icons import orbit_icon

app = QApplication([])
png = root / 'assets' / 'orbit.png'
orbit_icon().pixmap(256, 256).save(str(png))
with Image.open(png) as image:
    image.save(root / 'assets' / 'orbit.ico', format='ICO',
               sizes=[(size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
print('Ícones PNG e ICO gerados a partir de assets/orbit.svg.')
