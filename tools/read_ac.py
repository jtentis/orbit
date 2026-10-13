import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import cbor2
from aircon.identity import client_identity
from smartthings_local.protocol.dtls_session import DtlsCoapSession

identity = client_identity()
session = DtlsCoapSession('192.168.15.13', 49154, cert_pem=identity['cert'], key_pem=identity['key'])
try:
    session.connect()
    session.start_reader()
    resources = {}
    for path in ['/oic/d', '/oic/res', '/device/0']:
        code, body = session.get(path.strip('/').split('/'), timeout=8)
        resources[path] = {'code': code, 'body': cbor2.loads(body) if body else None}
    Path('local-report.json').write_text(json.dumps(resources, indent=2, default=str), encoding='utf-8')
    print(json.dumps(resources, indent=2, default=str))
finally:
    session.close()
