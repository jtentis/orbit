"""Per-user interactive logon task, with migration from the legacy Run entry."""
import getpass
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import winreg
from xml.etree import ElementTree as ET

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'WindFreeTray'
TASK_NAME = NAME+'-'+getpass.getuser()
NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
_enabled_cache = None


def _run_task(*args):
    executable = Path(os.environ['SystemRoot'])/'System32'/'schtasks.exe'
    return subprocess.run([str(executable), *args], capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)


def _query_task():
    result = _run_task('/Query', '/TN', TASK_NAME, '/XML')
    if result.returncode: return None
    data = result.stdout
    if isinstance(data, bytes):
        data = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-16-le' if b'\x00' in data else 'utf-8-sig', errors='replace')
    return ET.fromstring(data.strip())


def _legacy_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            winreg.QueryValueEx(key, NAME)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run') as key:
                state, _ = winreg.QueryValueEx(key, NAME)
                if isinstance(state, bytes) and state[:1] in (b'\x03', b'\x07'): return False
        except FileNotFoundError: pass
        return True
    except FileNotFoundError: return False


def _remove_legacy():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, NAME)
    except FileNotFoundError: pass


def _command():
    if getattr(sys, 'frozen', False): return [sys.executable, '--startup'], Path(sys.executable).parent
    root = Path(__file__).resolve().parents[1]
    return [str(Path(sys.executable).with_name('pythonw.exe')), str(root/'main.py'), '--startup'], root


def _task_xml():
    args, directory = _command()
    domain = os.environ.get('USERDOMAIN', '')
    user = (domain+'\\' if domain else '')+getpass.getuser()
    task = ET.fromstring(f'''<Task version="1.2" xmlns="{NS}">
      <RegistrationInfo><Description>WindFree Tray: controles locais ao entrar no Windows.</Description></RegistrationInfo>
      <Triggers><LogonTrigger><Enabled>true</Enabled><UserId/><Delay>PT15S</Delay></LogonTrigger></Triggers>
      <Principals><Principal id="User"><UserId/><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
      <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
        <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable>
        <Enabled>true</Enabled><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
        <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
      </Settings>
      <Actions Context="User"><Exec><Command/><Arguments/><WorkingDirectory/></Exec></Actions>
    </Task>''')
    for node in task.findall(f'.//{{{NS}}}UserId'): node.text = user
    for field, value in [('Command', args[0]), ('Arguments', subprocess.list2cmdline(args[1:])), ('WorkingDirectory', str(directory))]:
        task.find(f'.//{{{NS}}}{field}').text = value
    ET.register_namespace('', NS)
    return ET.tostring(task, encoding='utf-16', xml_declaration=True)


def enabled():
    global _enabled_cache
    if _enabled_cache is None:
        try:
            task = _query_task()
            _enabled_cache = task.findtext(f'{{{NS}}}Settings/{{{NS}}}Enabled') != 'false' if task is not None else _legacy_enabled()
        except (OSError, subprocess.SubprocessError, ET.ParseError):
            _enabled_cache = _legacy_enabled()
    return _enabled_cache


def set_enabled(value):
    global _enabled_cache
    if value:
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as file:
            file.write(_task_xml()); path = Path(file.name)
        try: result = _run_task('/Create', '/TN', TASK_NAME, '/XML', str(path), '/F')
        finally: path.unlink(missing_ok=True)
        if result.returncode:
            raise RuntimeError('Não foi possível ativar a inicialização pelo Agendador do Windows.')
    elif _query_task() is not None:
        if _run_task('/Delete', '/TN', TASK_NAME, '/F').returncode:
            raise RuntimeError('Não foi possível desativar a inicialização pelo Agendador do Windows.')
    _remove_legacy()
    _enabled_cache = bool(value)
    LOG.info('[startup] stage=registration enabled=%s task=%s', value, TASK_NAME)


def ensure_current():
    task = _query_task()
    if task is None:
        if _legacy_enabled(): set_enabled(True)
        return
    if task.findtext(f'{{{NS}}}Settings/{{{NS}}}Enabled') == 'false': return
    args, directory = _command()
    existing = task.find(f'.//{{{NS}}}Exec')
    if existing is None or any(existing.findtext(f'{{{NS}}}{key}') != value for key, value in
        [('Command', args[0]), ('Arguments', subprocess.list2cmdline(args[1:])), ('WorkingDirectory', str(directory))]):
        set_enabled(True)
