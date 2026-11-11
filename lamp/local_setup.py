"""Local commissioning stays in the same popup; no Samsung token is required."""
import json
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QFileDialog
from shared.ui import IconButton, Choice, SUBTLE, ERROR, ACCENT


class LocalLampSetup(QWidget):
    searchRequested = Signal()
    connectRequested = Signal(dict, str)
    helpRequested = Signal()
    disconnectRequested = Signal()
    reconnectRequested = Signal()

    def __init__(self, panel):
        super().__init__(); self.setObjectName('Page')
        self.panel = panel; self.info = None; self.saved = False; self.editing = False
        layout = QVBoxLayout(self); layout.setContentsMargins(22, 16, 22, 16); layout.setSpacing(10)
        header = QHBoxLayout(); back = IconButton('back', 'Voltar à lâmpada', size=30)
        back.clicked.connect(self.back); header.addWidget(back)
        self.heading = panel.text('Conexão', 'Title'); header.addWidget(self.heading, 1)
        close = IconButton('close', 'Fechar painel', size=30); close.clicked.connect(panel.dismiss); header.addWidget(close)
        layout.addLayout(header)
        self.summary = QWidget(); summary = QVBoxLayout(self.summary)
        summary.setContentsMargins(0, 12, 0, 0); summary.setSpacing(8)
        self.device_name = panel.text('Lâmpada', 'Title'); self.device_name.setWordWrap(True); summary.addWidget(self.device_name)
        summary.addWidget(panel.text('Smarteck SLAMP1 · Wi-Fi local', 'Muted'))
        self.connection_reading = panel.text('Conectada', 'Section'); summary.addWidget(self.connection_reading)
        self.recovery = panel.text('A reconexão acontece automaticamente.', 'Small')
        self.recovery.setWordWrap(True); summary.addWidget(self.recovery)
        summary.addSpacing(8)
        self.retry = QPushButton('Reconectar'); self.retry.setObjectName('Primary')
        self.retry.clicked.connect(self.reconnectRequested.emit); summary.addWidget(self.retry)
        self.change = QPushButton('Alterar conexão'); self.change.clicked.connect(self.edit)
        summary.addWidget(self.change); layout.addWidget(self.summary)
        self.form = QWidget(); form = QVBoxLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0); form.setSpacing(10)
        intro = panel.text('Encontre a lâmpada no Wi-Fi e informe a chave uma vez.', 'Muted')
        intro.setWordWrap(True); form.addWidget(intro)
        self.search = QPushButton('Buscar lâmpada'); self.search.clicked.connect(self.searchRequested.emit); form.addWidget(self.search)
        self.found = Choice(); self.found.setAccessibleName('Dispositivos Tuya encontrados')
        self.found.addItem('Selecione a lâmpada encontrada', None); self.found.currentIndexChanged.connect(self.selection_changed)
        form.addWidget(self.found)
        form.addWidget(panel.text('Chave da lâmpada', 'Section'))
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.EchoMode.Password); self.key.setMaxLength(64)
        self.key.setPlaceholderText('Chave local Tuya'); self.key.setAccessibleName('Chave local Tuya da lâmpada')
        self.key.setToolTip('Chave local de 16 bytes. Não é a senha do Wi-Fi.')
        form.addWidget(self.key); form.addWidget(panel.text('A chave fica salva e protegida neste Windows.', 'Small'))
        self.connect = QPushButton('Conectar lâmpada'); self.connect.setObjectName('Primary')
        self.connect.clicked.connect(self.submit); self.key.returnPressed.connect(self.submit); form.addWidget(self.connect)
        self.status = panel.text('Busque a lâmpada para configurar', 'Small'); self.status.setWordWrap(True); form.addWidget(self.status)
        self.more = QPushButton('Mais opções'); self.more.setObjectName('Quiet'); self.more.setCheckable(True)
        self.more.toggled.connect(self.toggle_more); form.addWidget(self.more)
        self.advanced = QWidget(); advanced = QVBoxLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0); advanced.setSpacing(8)
        self.import_button = QPushButton('Importar chave de um arquivo'); self.import_button.clicked.connect(self.import_key); advanced.addWidget(self.import_button)
        self.help_button = QPushButton('Como obter a chave'); self.help_button.clicked.connect(self.helpRequested.emit); advanced.addWidget(self.help_button)
        self.cloud = QPushButton('Usar SmartThings'); self.cloud.clicked.connect(lambda: panel.show_page(3)); advanced.addWidget(self.cloud)
        self.disconnect = QPushButton('Remover conexão'); self.disconnect.clicked.connect(lambda: self.forget_confirmation.show()); advanced.addWidget(self.disconnect)
        self.forget_confirmation = QWidget(); forget = QVBoxLayout(self.forget_confirmation)
        forget.setContentsMargins(0, 4, 0, 0)
        warning = panel.text('Para conectar novamente, você precisará da chave.', 'Small'); warning.setWordWrap(True); forget.addWidget(warning)
        actions = QHBoxLayout(); cancel = QPushButton('Cancelar'); cancel.clicked.connect(self.forget_confirmation.hide)
        self.confirm_forget = QPushButton('Remover'); self.confirm_forget.clicked.connect(self.disconnectRequested.emit)
        actions.addWidget(cancel); actions.addWidget(self.confirm_forget); forget.addLayout(actions)
        advanced.addWidget(self.forget_confirmation); self.forget_confirmation.hide()
        form.addWidget(self.advanced); self.advanced.hide(); layout.addWidget(self.form)
        layout.addStretch(1); self.summary.hide()

    @property
    def compact(self): return self.saved and not self.editing

    def update_visibility(self):
        self.summary.setVisible(self.compact); self.form.setVisible(not self.compact)
        self.heading.setText('Alterar conexão' if self.saved and self.editing else 'Conexão')
        self.panel.fit_visible_page()

    def opened(self):
        self.editing = False; self.key.clear(); self.more.setChecked(False); self.forget_confirmation.hide()
        self.update_visibility()

    def edit(self):
        self.editing = True; self.update_visibility(); self.search.setFocus()

    def back(self):
        if self.saved and self.editing: self.opened(); self.change.setFocus()
        else: self.panel.back_from_lamp()

    def toggle_more(self, checked):
        self.advanced.setVisible(checked)
        self.more.setText('Menos opções' if checked else 'Mais opções')
        if not checked: self.forget_confirmation.hide()

    def focus_default(self):
        if self.compact: (self.retry if not self.retry.isHidden() else self.change).setFocus()
        else: self.search.setFocus()

    def selection_changed(self):
        self.info = self.found.currentData()
        self.found.setToolTip(f"ID {self.info['device_id']} · protocolo {self.info['version']}" if self.info else '')

    def set_found(self, devices, selected=None):
        self.found.clear(); self.found.addItem('Selecione o dispositivo' if devices else 'Nenhum dispositivo Tuya encontrado', None)
        for info in devices:
            name = info['name'] if not info['name'].startswith('Dispositivo Tuya') else 'Dispositivo Wi-Fi'
            if len(devices) > 1: name += ' · '+info['host']
            self.found.addItem(name, info)
        if len(devices) == 1: self.found.setCurrentIndex(1)
        elif selected:
            for index in range(1, self.found.count()):
                if self.found.itemData(index).get('device_id') == selected.get('device_id'): self.found.setCurrentIndex(index); break

    def submit(self):
        if not self.info:
            self.status.show(); self.status.setText('Busque e selecione a lâmpada antes de conectar.'); return
        key = self.key.text()
        if len(key.encode('utf-8')) != 16:
            self.status.show(); self.status.setText('Informe a chave local de 16 bytes.'); self.key.setFocus(); return
        self.key.clear(); self.connectRequested.emit(dict(self.info), key)

    def import_key(self):
        if not self.info:
            self.status.show(); self.status.setText('Primeiro selecione o dispositivo encontrado.'); return
        # The popup panel closes when the dialog activates and takes an owned native dialog with it.
        self.panel.hide()
        filename, _ = QFileDialog.getOpenFileName(None, 'Importar chave local', '', 'Dispositivos Tuya (*.json)')
        self.panel.show(); self.panel.raise_(); self.panel.activateWindow()
        if not filename: return
        try:
            if Path(filename).stat().st_size > 1024*1024: raise ValueError()
            data = json.loads(Path(filename).read_text(encoding='utf-8-sig'))
            items = data if isinstance(data, list) else data.get('devices', [])
            item = next(item for item in items if item.get('id') == self.info['device_id'])
            key = item.get('key') or item.get('local_key')
            if not isinstance(key, str) or len(key.encode('utf-8')) != 16: raise ValueError()
        except Exception:
            self.status.show(); self.status.setText('O arquivo não contém uma chave válida para o dispositivo escolhido.'); return
        self.key.setText(key); self.status.show(); self.status.setText('Chave importada. Clique em Conectar lâmpada.')

    def render(self, busy, message, info, error=False, operation=None, *, configured=False, online=False):
        self.saved = configured and info.get('provider') == 'local' and bool(info.get('device_id'))
        self.device_name.setText(info.get('name') or 'Smarteck SLAMP1')
        self.connection_reading.setText('● Conectada' if online else 'Conectando…' if busy else 'Sem conexão')
        self.connection_reading.setStyleSheet(f'color: {(ACCENT if online else ERROR if error else SUBTLE).name()};')
        self.recovery.setVisible(not online); self.retry.setVisible(not online); self.retry.setEnabled(not busy)
        self.change.setEnabled(not busy)
        self.update_visibility()
        self.status.setText(message); self.status.setStyleSheet(f'color: {(ERROR if error else SUBTLE).name()}; font-size: 11px;')
        self.status.setVisible(busy or error or operation == 'discover_local')
        self.search.setText('Buscando na rede…' if busy and operation == 'discover_local' else 'Buscar lâmpada')
        for widget in (self.search, self.found, self.key, self.connect, self.import_button, self.help_button, self.cloud, self.confirm_forget): widget.setEnabled(not busy)
        self.disconnect.setVisible(info.get('provider') == 'local'); self.disconnect.setEnabled(not busy)
        if info.get('provider') == 'local' and all(info.get(key) for key in ('device_id', 'host', 'version', 'name')) and self.found.count() == 1:
            self.set_found([info], info)

    def hideEvent(self, event):
        self.key.clear(); super().hideEvent(event)
