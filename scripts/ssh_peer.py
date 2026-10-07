"""Validate the actual SSH session record before changing host access policy."""
import ipaddress
import json
import sys


def validate_connection(connection, cidrs):
    if not isinstance(connection, str) or len(connection.split()) != 4:
        raise ValueError('SSH_CONNECTION must contain client IP/port and server IP/port')
    client, client_port, server, server_port = connection.split()
    peer = ipaddress.ip_address(client)
    ipaddress.ip_address(server)
    for port in (client_port, server_port):
        if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise ValueError('SSH_CONNECTION contains an invalid TCP port')
    if not isinstance(cidrs, list) or not cidrs:
        raise ValueError('admin_cidrs must contain at least one administrator network')
    networks = [ipaddress.ip_network(cidr, strict=False) for cidr in cidrs]
    if not any(peer in network for network in networks):
        raise ValueError('SSH peer is outside admin_cidrs')
    return str(peer)


def main():
    try:
        data = json.load(sys.stdin)
        peer = validate_connection(data['connection'], data['cidrs'])
    except (ValueError, KeyError, TypeError) as error:
        print(f'[BLOCKED] {error}', file=sys.stderr)
        return 2
    print(f'PASS: SSH peer {peer} is within admin_cidrs')
    return 0


if __name__ == '__main__':
    sys.exit(main())
