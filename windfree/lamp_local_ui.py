"""Local commissioning stays in the same popup; no Samsung token is required."""
import json
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QFileDialog
from .ui import IconButton, Choice, SUBTLE, ERROR


class LocalLampSetup(QWidget):
    searchRequested = Signal()
    connectRequested = Signal(dict, str)
    helpRequested = Signal()
    disconnectRequested = Signal()

    def __init__(self, panel):
        super().__init__(); self.setObjectName('Page')
        self.panel = panel; self.info = None
        layout = QVBoxLayout(self); layout.setContentsMargins(22, 16, 22, 16); layout.setSpacing(10)
        header = QHBoxLayout(); back = IconButton('back', 'Voltar à lâmpada', size=30)
        back.clicked.connect(lambda: panel.show_page(2)); header.addWidget(back)
        header.addWidget(panel.text('Conexão local', 'Title'), 1)
        close = IconButton('close', 'Fechar painel', size=30); close.clicked.connect(panel.dismiss); header.addWidget(close)
        layout.addLayout(header)
        intro = panel.text('Controle pelo Wi-Fi, sem token Samsung. A busca encontra o IP; a chave local autentica a conexão com a lâmpada.', 'Muted')
        intro.setWordWrap(True); layout.addWidget(intro)
        self.search = QPushButton('Buscar dispositivos Tuya na rede'); self.search.clicked.connect(self.searchRequested.emit); layout.addWidget(self.search)
        layout.addWidget(panel.text('Dispositivo encontrado', 'Section'))
        self.found = Choice(); self.found.setAccessibleName('Dispositivos Tuya encontrados')
        self.found.addItem('Busque a lâmpada na rede', None); self.found.currentIndexChanged.connect(self.selection_changed)
        layout.addWidget(self.found)
        self.identity = panel.text('A conexão verificará os recursos RGB da lâmpada.', 'Small'); self.identity.setWordWrap(True); layout.addWidget(self.identity)
        panel.separator(layout)
        layout.addWidget(panel.text('Chave local Tuya', 'Section'))
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.EchoMode.Password); self.key.setMaxLength(64)
        self.key.setPlaceholderText('Chave local de 16 bytes'); self.key.setAccessibleName('Chave local Tuya da lâmpada')
        layout.addWidget(self.key)
        explanation = panel.text('Obtida uma vez na plataforma Tuya ou em uma configuração local existente. Não é a senha do Wi-Fi. A busca não consegue extrair essa chave.', 'Small')
        explanation.setWordWrap(True); layout.addWidget(explanation)
        self.connect = QPushButton('Conectar lâmpada local'); self.connect.setObjectName('Primary')
        self.connect.clicked.connect(self.submit); self.key.returnPressed.connect(self.submit); layout.addWidget(self.connect)
        self.import_button = QPushButton('Importar chave de devices.json'); self.import_button.clicked.connect(self.import_key); layout.addWidget(self.import_button)
        help_button = QPushButton('Como obter a chave local'); help_button.clicked.connect(self.helpRequested.emit); layout.addWidget(help_button)
        self.status = panel.text('Busque a lâmpada para configurar', 'Small'); self.status.setWordWrap(True); layout.addWidget(self.status)
        layout.addStretch(1); panel.separator(layout)
        self.disconnect = QPushButton('Desconectar lâmpada e apagar chave')
        self.disconnect.clicked.connect(self.disconnectRequested.emit); self.disconnect.hide(); layout.addWidget(self.disconnect)
        cloud = QPushButton('Conectar pelo SmartThings'); cloud.clicked.connect(lambda: panel.show_page(3)); layout.addWidget(cloud)

    def selection_changed(self):
        self.info = self.found.currentData()
        self.identity.setText(f"ID {self.info['device_id']} · protocolo {self.info['version']}" if self.info else 'A conexão verificará os recursos RGB da lâmpada.')

    def set_found(self, devices, selected=None):
        self.found.clear(); self.found.addItem('Selecione o dispositivo' if devices else 'Nenhum dispositivo Tuya encontrado', None)
        for info in devices: self.found.addItem(info['name'], info)
        if len(devices) == 1: self.found.setCurrentIndex(1)  # Discovery does not send actuator commands.
        elif selected:
            for index in range(1, self.found.count()):
                if self.found.itemData(index).get('device_id') == selected.get('device_id'): self.found.setCurrentIndex(index); break

    def submit(self):
        if not self.info:
            self.status.setText('Busque e selecione a lâmpada antes de conectar.'); return
        key = self.key.text()
        if len(key.encode('utf-8')) != 16:
            self.status.setText('Informe a chave local de 16 bytes.'); self.key.setFocus(); return
        self.key.clear(); self.connectRequested.emit(dict(self.info), key)

    def import_key(self):
        if not self.info:
            self.status.setText('Primeiro selecione o dispositivo encontrado.'); return
        filename, _ = QFileDialog.getOpenFileName(self, 'Importar chave local', '', 'Dispositivos Tuya (*.json)')
        if not filename: return
        try:
            if Path(filename).stat().st_size > 1024*1024: raise ValueError()
            data = json.loads(Path(filename).read_text(encoding='utf-8-sig'))
            items = data if isinstance(data, list) else data.get('devices', [])
            item = next(item for item in items if item.get('id') == self.info['device_id'])
            key = item.get('key') or item.get('local_key')
            if not isinstance(key, str) or len(key.encode('utf-8')) != 16: raise ValueError()
        except Exception:
            self.status.setText('O arquivo não contém uma chave válida para o dispositivo escolhido.'); return
        self.key.setText(key); self.status.setText('Chave importada. Clique em Conectar lâmpada local.')

    def render(self, busy, message, info, error=False, operation=None):
        self.status.setText(message); self.status.setStyleSheet(f'color: {(ERROR if error else SUBTLE).name()}; font-size: 11px;')
        self.search.setText('Buscando na rede…' if busy and operation == 'discover_local' else 'Buscar dispositivos Tuya na rede')
        for widget in (self.search, self.found, self.key, self.connect, self.import_button): widget.setEnabled(not busy)
        self.disconnect.setVisible(info.get('provider') == 'local'); self.disconnect.setEnabled(not busy)
        if info.get('provider') == 'local' and all(info.get(key) for key in ('device_id', 'host', 'version', 'name')) and self.found.count() == 1:
            self.set_found([info], info)
