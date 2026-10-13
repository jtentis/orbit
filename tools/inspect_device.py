import json
import cbor2
from smartthings_local.protocol.ocf_discovery import discover_ocf_secure_ports, read_plaintext_ocf_resource
from smartthings_local.protocol.dtls_probe import probe_dtls_ports

for host in ['192.168.15.4', '192.168.15.13']:
    r = discover_ocf_secure_ports(host, timeout=3)
    print(host, r.ports, flush=True)
    print(probe_dtls_ports(host, r.ports, timeout=2), flush=True)
    d = read_plaintext_ocf_resource(host, '/oic/d', timeout=2)
    print(d, flush=True)
    print(cbor2.loads(d.payload) if d.payload else None, flush=True)
