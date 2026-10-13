"""Read-only, bounded probe of the user's LAN for Samsung OCF endpoints."""
import concurrent.futures
import json
import sys
from smartthings_local.protocol.dtls_probe import probe_dtls_ports


def probe(host):
    try:
        result = probe_dtls_ports(host, (49153, 49154, 49155, 49152, 49156), timeout=0.7, retries=0)
        if result.responder_ports:
            return {"host": host, "ports": list(result.responder_ports)}
    except Exception:
        pass
    return None


if __name__ == "__main__":
    prefix = sys.argv[1] if len(sys.argv) > 1 else "192.168.15"
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        for result in pool.map(probe, (f"{prefix}.{i}" for i in range(1, 255))):
            if result:
                print(json.dumps(result), flush=True)
