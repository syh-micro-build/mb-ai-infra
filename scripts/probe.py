#!/usr/bin/env python3
"""Run from an independent machine; positive controls precede negative port probes."""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import sys

from infra import require, run
from render import load_config


def probe(config, addresses, timeout=4):
    checks = []
    domain = config['domain']
    blocked = sorted({2375, 2376, 5432, 6379, *[c['upstream']['port'] for c in config['contracts']]})
    for address in addresses:
        ip = ipaddress.ip_address(address)
        literal = f'[{ip}]' if ip.version == 6 else str(ip)
        positive = True
        for scheme, port, path, expected in [('http', 80, '/', 308)] + [('https', 443, c['health']['path'], c['health']['expected_status']) for c in config['contracts']]:
            name = f'{address} {scheme} {path}'
            try:
                status = run(['curl', '--noproxy', '*', '-sS', '--max-time', str(timeout * 3), '--resolve', f'{domain}:{port}:{literal}',
                              '-o', '/dev/null', '-w', '%{http_code}', f'{scheme}://{domain}{path}'])
                require(status == str(expected), f'HTTP {status}')
                checks.append(dict(name=name, status='PASS'))
            except Exception as error:
                positive = False
                checks.append(dict(name=name, status='FAIL', detail=str(error)))
        for port in blocked:
            if not positive:
                checks.append(dict(name=f'{address}:{port}', status='BLOCKED', detail='Positive controls failed; cannot claim firewall success'))
                continue
            try:
                with socket.create_connection((address, port), timeout=timeout):
                    checks.append(dict(name=f'{address}:{port}', status='FAIL', detail='Unexpected successful TCP connection'))
            except OSError:
                checks.append(dict(name=f'{address}:{port}', status='PASS', detail='No TCP connection from this probe location'))
    return dict(addresses=addresses, checks=checks, result='PASS' if checks and all(c['status'] == 'PASS' for c in checks) else 'FAIL')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--site', required=True)
    parser.add_argument('--address', action='append', help='Explicit migration destination; repeat for IPv4 and IPv6')
    parser.add_argument('--report', default='reports/external.json')
    args = parser.parse_args()
    config = load_config(args.site)
    addresses = args.address or sorted({entry[4][0] for entry in socket.getaddrinfo(config['domain'], None, type=socket.SOCK_STREAM)})
    result = probe(config, addresses)
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['result'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
