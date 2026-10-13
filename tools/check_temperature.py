import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cbor2
from aircon.device import Device, V

device = Device()
try:
    device.connect(sys.argv[1])
    original = device.refresh().temperature
    def read():
        for path in ['/temperature/desired/0', '/temperatures/vs/0']:
            print(path, device.read(path), flush=True)
    read()
    try:
        payload = {V + 'items': [{V + 'id': '0', V + 'desired': str(original + 1)}]}
        print('Vendor write', device.session.post(['temperatures', 'vs', '0'], cbor2.dumps(payload), timeout=8), flush=True)
        time.sleep(2)
        read()
        time.sleep(5)
        read()
    finally:
        print('Restore', device.session.post(['temperatures', 'vs', '0'], cbor2.dumps({V + 'items': [{V + 'id': '0', V + 'desired': str(original)}]}), timeout=8), flush=True)
        time.sleep(2)
        read()
finally:
    device.close()
