#!/usr/bin/env python3
"""Manage one owned chain per family; preserve UFW, Docker and all unrelated rules."""
import argparse
import contextlib
import ipaddress
import json
from pathlib import Path
import subprocess
import shlex
import sys

CHAIN = 'MB_AI_INFRA'
HOST_CHAIN = 'MB_AI_HOST'


def rules(config):
    result = [['-m', 'conntrack', '--ctstate', 'RELATED,ESTABLISHED', '-j', 'RETURN']]
    for interface in config['public_interfaces']:
        for port in config['public_tcp_ports']:
            result.append(['-i', interface, '-p', 'tcp', '-m', 'conntrack', '--ctorigdstport', str(port), '-j', 'RETURN'])
        result.append(['-i', interface, '-j', 'DROP'])
    result.append(['-j', 'RETURN'])
    return result


def host_rules(config, version):
    result = [['-i', 'lo', '-j', 'RETURN'], ['-m', 'conntrack', '--ctstate', 'RELATED,ESTABLISHED', '-j', 'RETURN']]
    for interface in config['public_interfaces']:
        protocol = 'icmp' if version == 4 else 'ipv6-icmp'
        result.append(['-i', interface, '-p', protocol, '-j', 'RETURN'])
        result.append(['-i', interface, '-p', 'udp', '--dport', '68' if version == 4 else '546', '-j', 'RETURN'])
        for cidr in config['admin_cidrs']:
            if ipaddress.ip_network(cidr, strict=False).version == version:
                result.append(['-i', interface, '-s', str(ipaddress.ip_network(cidr, strict=False)), '-p', 'tcp', '--dport', str(config['ssh_port']), '-j', 'RETURN'])
        for port in config['public_tcp_ports']:
            result.append(['-i', interface, '-p', 'tcp', '--dport', str(port), '-j', 'RETURN'])
        result.append(['-i', interface, '-j', 'DROP'])
    result.append(['-j', 'RETURN'])
    return result


def hooks():
    return [('INPUT', HOST_CHAIN), ('DOCKER-USER', CHAIN), ('FORWARD', 'DOCKER-USER')]


def canonical(tokens):
    pairs = []
    for index in range(0, len(tokens), 2):
        key, value = tokens[index:index + 2]
        if key == '-m' and value in ('tcp', 'udp'):
            continue
        if key == '--ctstate':
            value = ','.join(sorted(value.split(',')))
        if key == '-s':
            value = str(ipaddress.ip_network(value, strict=False))
        pairs.append((key, value))
    return sorted(pairs)


def execute(argv, data=None, check=True):
    proc = subprocess.run(argv, input=data, text=True, capture_output=True, timeout=30)
    if check and proc.returncode:
        raise RuntimeError(f'{argv[0]} failed: {proc.stderr.strip()}')
    return proc


def apply(config):
    import fcntl
    with Path('/run/mb-ai-docker-guard.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for binary, version in (('iptables', 4), ('ip6tables', 6)):
            # Precreate the documented user hook before Docker starts, including IPv6.
            if execute([binary, '-w', '10', '-S', 'DOCKER-USER'], check=False).returncode:
                execute([binary, '-w', '10', '-N', 'DOCKER-USER'])
            content = '*filter\n'
            for chain, body in ((CHAIN, rules(config)), (HOST_CHAIN, host_rules(config, version))):
                content += ':' + chain + ' - [0:0]\n-F ' + chain + '\n'
                content += '\n'.join('-A ' + chain + ' ' + ' '.join(rule) for rule in body) + '\n'
            content += 'COMMIT\n'
            execute([binary + '-restore', '--wait', '10', '--noflush'], data=content)
            for parent, target in hooks():
                lines = execute([binary, '-w', '10', '-S', parent]).stdout.splitlines()
                entries = [line for line in lines if line.startswith('-A ')]
                if not entries or entries[0] != f'-A {parent} -j {target}':
                    while execute([binary, '-w', '10', '-C', parent, '-j', target], check=False).returncode == 0:
                        execute([binary, '-w', '10', '-D', parent, '-j', target])
                    execute([binary, '-w', '10', '-I', parent, '1', '-j', target])


def verify(config):
    for binary, version in (('iptables', 4), ('ip6tables', 6)):
        for parent, target in hooks():
            execute([binary, '-w', '10', '-C', parent, '-j', target])
            entries = [line for line in execute([binary, '-w', '10', '-S', parent]).stdout.splitlines() if line.startswith('-A ')]
            if entries[0] != f'-A {parent} -j {target}':
                raise RuntimeError(f'{binary}: guard hook is not first in {parent}')
        for chain, body in ((CHAIN, rules(config)), (HOST_CHAIN, host_rules(config, version))):
            for rule in body:
                execute([binary, '-w', '10', '-C', chain, *rule])
            actual = execute([binary, '-w', '10', '-S', chain]).stdout.splitlines()
            actual_body = [canonical(shlex.split(line)[2:]) for line in actual if line.startswith('-A ')]
            if actual_body != [canonical(rule) for rule in body]:
                raise RuntimeError(f'{binary}: guard content or ordering differs from policy')
    print('PASS IPv4 and IPv6 Docker guard')


def main():
    from infra import validate_config
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['apply', 'verify'])
    parser.add_argument('--config')
    args = parser.parse_args()
    with open(args.config) if args.config else contextlib.nullcontext(sys.stdin) as stream:
        config = validate_config(json.load(stream))
    (apply if args.action == 'apply' else verify)(config)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'FAIL Docker guard: {exc}', file=sys.stderr)
        sys.exit(1)
