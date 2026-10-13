"""Local client identity, following LocalThings' public protocol research."""
import re
import socket
import ssl
import uuid as uuid_module
import threading
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from .storage import load_secret, save_secret

_IDENTITY_LOCK = threading.Lock()


def client_identity() -> dict:
    with _IDENTITY_LOCK:
        return _load_or_create_identity()


def _load_or_create_identity() -> dict:
    existing = load_secret('identity')
    if existing:
        return existing
    host = 'connect-v2.samsungiotcloud.com'
    # Samsung serves a private chain; this reads only its public subject UUID.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            cert = x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))
    identity = None
    for attr in cert.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME):
        match = re.search(r'uuid:([0-9a-fA-F-]{36})', attr.value)
        if match:
            identity = str(uuid_module.UUID(match.group(1)))
            break
    if not identity:
        raise RuntimeError('O certificado público da Samsung não informou a identidade OCF.')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, 'KR'),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Samsung Electronics'),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f'uuid:{identity}'),
        x509.NameAttribute(NameOID.COMMON_NAME, f'urn:uuid:{identity}'),
    ])
    now = datetime.now(timezone.utc)
    leaf = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650)).sign(key, hashes.SHA256()))
    material = {
        'cert': leaf.public_bytes(serialization.Encoding.PEM).decode(),
        'key': key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()).decode(),
    }
    save_secret('identity', material)
    return material
