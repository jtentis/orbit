"""Per-user settings and credentials protected by Windows DPAPI."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'WindFreeTray'


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('O armazenamento seguro requer Windows.')
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        description = ctypes.c_void_p()
        args = (ctypes.byref(source), ctypes.byref(description), None, None, None, 1, ctypes.byref(result))
    else:
        fn = crypt.CryptProtectData
        args = (ctypes.byref(source), 'WindFree Tray', None, None, None, 1, ctypes.byref(result))
    if not fn(*args):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)
        if decrypt and description.value:
            kernel.LocalFree(description)


def save_secret(name: str, value: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = DATA_DIR / f'{name}.dpapi'
    temp = target.with_suffix('.tmp')
    temp.write_bytes(_protect(json.dumps(value).encode()))
    os.replace(temp, target)


def load_secret(name: str) -> dict | None:
    path = DATA_DIR / f'{name}.dpapi'
    return json.loads(_protect(path.read_bytes(), decrypt=True)) if path.exists() else None


def load_config() -> dict:
    path = DATA_DIR / 'config.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def save_config(config: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / 'config.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)
