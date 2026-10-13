import os
from pathlib import Path
import subprocess
import sys
import winreg

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'WindFreeTray'


def enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            winreg.QueryValueEx(key, NAME)
        return True
    except FileNotFoundError:
        return False


def set_enabled(value: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        if value:
            if getattr(sys, 'frozen', False):
                args = [sys.executable]
            else:
                executable = Path(sys.executable).with_name('pythonw.exe')
                args = [str(executable), str(Path(__file__).resolve().parents[1] / 'main.py')]
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
