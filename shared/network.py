import ipaddress


def validate_host(host: str) -> str:
    address = ipaddress.ip_address(host.strip())
    if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
        raise ValueError('Informe um endereço IPv4 da sua rede local.')
    return str(address)
