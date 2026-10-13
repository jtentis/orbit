"""Find air conditioners through public, read-only OCF discovery."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import socket
import subprocess
import cbor2
from smartthings_local.protocol.ocf_discovery import discover_ocf_secure_ports, read_plaintext_ocf_resource
from smartthings_local.protocol.dtls_probe import probe_dtls_ports
from smartthings_local.protocol.dtls_session import DtlsCoapSession
from .identity import client_identity
from shared.network import validate_host




def inspect_host(host: str, timeout: float = 1.2) -> dict | None:
    host = validate_host(host)
    try:
        identity = read_plaintext_ocf_resource(host, '/oic/d', timeout=timeout, retries=1)
        if not identity.successful or not identity.payload:
            return inspect_secure_host(host, timeout)
        device = cbor2.loads(identity.payload)
        if not isinstance(device, dict) or 'oic.d.airconditioner' not in device.get('rt', []):
            return None
        ports = discover_ocf_secure_ports(host, timeout=timeout, retries=1)
        if not ports.ports:
            return None
        return {'host': host, 'port': ports.ports[0], 'device_id': device.get('di'),
                'name': device.get('n', 'Samsung WindFree')}
    except (OSError, ValueError, TimeoutError):
        return None


def inspect_secure_host(host: str, timeout: float = 1.2) -> dict | None:
    """Firewall-friendly fallback: DTLS replies use the requested peer port."""
    session = None
    try:
        probe = probe_dtls_ports(host, (49154, 49153, 49155), timeout=timeout, retries=1)
        if not probe.selected_port:
            return None
        material = client_identity()
        session = DtlsCoapSession(host, probe.selected_port, cert_pem=material['cert'], key_pem=material['key'])
        session.connect()
        session.start_reader()
        code, body = session.get(['oic', 'd'], timeout=3)
        if code >> 5 != 2 or not body:
            return None
        device = cbor2.loads(body)
        if 'oic.d.airconditioner' not in device.get('rt', []):
            return None
        return {'host': host, 'port': probe.selected_port, 'device_id': device.get('di'),
                'name': device.get('n', 'Samsung WindFree')}
    except Exception:
        return None
    finally:
        if session:
            session.close()


def lan_hosts() -> list[str]:
    command = ('Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway} | '
               'ForEach-Object {$_.IPv4Address | Select-Object IPAddress,PrefixLength} | ConvertTo-Json -Compress')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError('Não encontrei uma rede ativa. Informe o IP do aparelho no menu Conexão.')
    interfaces = json.loads(result.stdout)
    if isinstance(interfaces, dict):
        interfaces = [interfaces]
    hosts = []
    for interface in interfaces:
        address = interface['IPAddress']
        prefix = max(24, int(interface['PrefixLength']))
        network = ipaddress.ip_network(f'{address}/{prefix}', strict=False)
        if network.is_private:
            hosts.extend(str(h) for h in network.hosts() if str(h) != address)
    return list(dict.fromkeys(hosts))[:508]


def discover(expected_id: str | None = None) -> list[dict]:
    found = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        for result in pool.map(inspect_host, lan_hosts()):
            if result and (not expected_id or result['device_id'] == expected_id):
                found.append(result)
    return found
