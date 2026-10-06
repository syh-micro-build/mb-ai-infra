#!/usr/bin/env python3
"""Infrastructure runtime. Application files, containers and versions are never managed."""
import argparse
import contextlib
import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path('/opt/mb-ai-infra')
RELEASE_FILES = {'config.json', 'compose.yaml', 'nginx/nginx.conf', 'nginx/conf.d/site.conf', 'nginx/conf.d/proxy.inc'}


def run(argv, **kwargs):
    result = subprocess.run([str(arg) for arg in argv], capture_output=True, text=True, timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(map(str, argv))}\n{result.stderr.strip()}")
    return result.stdout.strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(value):
    require(isinstance(value, str) and re.fullmatch(r'/[A-Za-z0-9_./-]+', value), 'Invalid absolute path')
    path = Path(value)
    require('..' not in path.parts, 'Path traversal is forbidden')
    for protected in ('/opt/sub2api', '/opt/mb-ai-docs'):
        require(path != Path(protected) and Path(protected) not in path.parents, 'Protected application boundary')
    return path


def validate_config(config):
    domain = config.get('domain', '')
    require(isinstance(domain, str) and len(domain) <= 253 and re.fullmatch(
        r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain), 'Invalid lowercase DNS domain')
    require(re.fullmatch(r'nginx:[A-Za-z0-9_.-]+@sha256:[a-f0-9]{64}', config.get('nginx_image', '')), 'Pin the official Nginx image by digest')
    for key in ('ssh_port', 'health_port'):
        require(type(config.get(key)) is int and 1 <= config[key] <= 65535, f'Invalid {key}')
    require(isinstance(config.get('public_tcp_ports'), list) and set(config['public_tcp_ports']) == {80, 443}, 'v1 public ports are 80/443 only')
    require(isinstance(config.get('public_interfaces'), list) and config['public_interfaces'], 'Specify public_interfaces explicitly')
    require(all(isinstance(x, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,14}', x) for x in config['public_interfaces']), 'Invalid interface')
    require(isinstance(config.get('admin_cidrs'), list) and config['admin_cidrs'], 'Specify admin_cidrs explicitly')
    for cidr in config['admin_cidrs']:
        ipaddress.ip_network(cidr, strict=False)
    safe_path(config['tls_root'])
    safe_path(config['acme_root'])
    require(re.fullmatch(r'[1-9][0-9]{0,3}m', config.get('client_max_body_size', '')), 'Invalid body size')
    for key, maximum in (('hsts_max_age', 31536000), ('certificate_min_days', 30)):
        require(type(config.get(key)) is int and 0 <= config[key] <= maximum, f'Invalid {key}')
    contracts = config.get('contracts', [])
    require(len(contracts) == 2, 'Exactly two independent application contracts are required')
    ports = {config['ssh_port'], config['health_port'], 80, 443}
    require(len(ports) == 4, 'SSH, Edge and health ports must be distinct')
    for contract, name, prefix in zip(contracts, ('sub2api', 'mb-ai-docs'), ('/', '/docs/')):
        require(contract['name'] == name and contract['edge']['path_prefix'] == prefix, 'Unsupported v1 contract identity or route')
        require(contract['upstream']['host'] == '127.0.0.1', 'Upstreams must use IPv4 loopback')
        port = contract['upstream']['port']
        require(type(port) is int and 1 <= port <= 65535 and port not in ports, 'Invalid or conflicting upstream port')
        ports.add(port)
        health = contract['health']
        require(re.fullmatch(r'/[A-Za-z0-9_./-]*', health['path']) and '..' not in health['path'], 'Invalid health path')
        require(type(health['expected_status']) is int and 200 <= health['expected_status'] < 400, 'Invalid health status')
    return config


def read_config(release):
    return validate_config(json.loads((release / 'config.json').read_text()))


def contract_check(config):
    errors = []
    for contract in config['contracts']:
        url = f"http://127.0.0.1:{contract['upstream']['port']}{contract['health']['path']}"
        try:
            # Do not follow redirects: the contract declares an exact HTTP response.
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            try:
                with opener.open(url, timeout=10) as response:
                    status = response.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            require(status == contract['health']['expected_status'], f'HTTP {status}')
        except (OSError, ValueError) as exc:
            errors.append(f"[BLOCKED] {contract['name']} contract unavailable: {exc}")
    if errors:
        raise RuntimeError('\n'.join(errors))


def smoke_check(release, runner=run):
    require(release is not None, 'No active Infra release')
    config = read_config(release)
    domain = config['domain']
    container_id = runner(['docker', 'compose', '-p', 'mb-ai-infra', '-f', release / 'compose.yaml', 'ps', '--status', 'running', '-q', 'edge'])
    require(container_id and len(container_id.split()) == 1, 'Exactly one running Infra Edge is required')
    container = json.loads(runner(['docker', 'inspect', container_id]))[0]
    require(container['State'].get('Health', {}).get('Status') == 'healthy', 'Infra Edge is unhealthy')
    require(container['Config']['Image'] == config['nginx_image'], 'Edge image differs from release contract')
    def curl(url, expected, port):
        status = runner(['curl', '--noproxy', '*', '--silent', '--show-error', '--max-time', '15',
                         '--resolve', f'{domain}:{port}:127.0.0.1', '--output', '/dev/null',
                         '--write-out', '%{http_code}', url])
        require(status == str(expected), f'{url}: expected {expected}, received {status}')
    curl(f"http://127.0.0.1:{config['health_port']}/healthz", 200, config['health_port'])
    if config.get('tls_enabled', True):
        curl(f'http://{domain}/', 308, 80)
        redirect = runner(['curl', '--noproxy', '*', '-sS', '--max-time', '15', '--resolve', f'{domain}:80:127.0.0.1',
                           '-o', '/dev/null', '-w', '%{redirect_url}', f'http://{domain}/'])
        require(redirect == f'https://{domain}/', 'Incorrect HTTPS redirect destination')
        for contract in config['contracts']:
            curl(f"https://{domain}{contract['health']['path']}", contract['health']['expected_status'], 443)
        certificate = Path(config['tls_root']) / 'live' / domain / 'fullchain.pem'
        runner(['openssl', 'x509', '-in', certificate, '-noout', '-checkend', str(config['certificate_min_days'] * 86400)])
    else:
        curl(f'http://{domain}/', 503, 80)
    challenge = Path(config['acme_root']) / '.well-known/acme-challenge'
    token = 'infra-probe-' + uuid.uuid4().hex
    probe = challenge / token
    probe.write_text(token)
    try:
        content = runner(['curl', '--noproxy', '*', '-fsS', '--max-time', '15', '--resolve', f'{domain}:80:127.0.0.1',
                          f'http://{domain}/.well-known/acme-challenge/{token}'])
        require(content == token, 'ACME webroot mapping failed')
    finally:
        probe.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(root):
    import fcntl
    root.mkdir(parents=True, exist_ok=True, mode=0o750)
    with (root / 'deployment.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def write_json(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(content, indent=2, sort_keys=True) + '\n')
    temp.chmod(0o600)
    os.replace(temp, path)


class Deployment:
    def __init__(self, root=ROOT, runner=run, verifier=smoke_check):
        self.root, self.run, self.verify = Path(root), runner, verifier
        require(not self.root.is_symlink(), 'Infrastructure root must not be a symlink')

    def release(self, value):
        path = Path(value)
        if not path.is_absolute():
            path = self.root / 'releases' / path
        require(path.parent == self.root / 'releases' and re.fullmatch(r'[A-Za-z0-9_.-]+', path.name), 'Release is outside infra root')
        require(path.is_dir() and not path.is_symlink(), 'Release must be an existing real directory')
        manifest = json.loads((path / 'manifest.json').read_text())
        require(set(manifest['files']) == RELEASE_FILES, 'Incomplete release manifest')
        for name, digest in manifest['files'].items():
            file = path / name
            require(file.resolve().is_relative_to(path.resolve()), 'Release file escapes boundary')
            require(hashlib.sha256(file.read_bytes()).hexdigest() == digest, f'Release checksum mismatch: {name}')
        read_config(path)
        return path

    def current(self):
        link = self.root / 'current'
        require(not link.exists() or link.is_symlink(), 'current must be an infra-owned symlink')
        return self.release(link.resolve()) if link.is_symlink() else None

    def compose(self, release, *args):
        return self.run(['docker', 'compose', '--project-name', 'mb-ai-infra', '--file', release / 'compose.yaml', *args])

    def switch(self, release):
        temp = self.root / '.current-next'
        temp.unlink(missing_ok=True)
        temp.symlink_to(release, target_is_directory=True)
        os.replace(temp, self.root / 'current')

    def legacy_snapshot(self, container, project):
        require(re.fullmatch(r'[A-Za-z0-9_.-]+', container), 'Invalid legacy container identity')
        info = json.loads(self.run(['docker', 'inspect', container]))[0]
        labels = info['Config'].get('Labels') or {}
        require(labels.get('com.docker.compose.project') == project and project not in ('mb-ai-infra', 'sub2api', 'mb-ai-docs'),
                'Legacy container does not belong to the declared legacy Edge project')
        image = info['Config']['Image'].removeprefix('docker.io/library/')
        require(image.startswith('nginx:') and info['State']['Running'], 'Legacy target must be a running Nginx Edge')
        legacy = Path('/opt/mb-ai-edge')
        require(legacy.is_dir() and not legacy.is_symlink(), 'Legacy Edge directory is absent or is a symlink')
        receipt = dict(container=info['Id'], restart=info['HostConfig']['RestartPolicy'], directory=str(legacy))
        return receipt

    def restore_legacy(self, legacy):
        policy = legacy['restart']['Name']
        if policy == 'on-failure' and legacy['restart'].get('MaximumRetryCount'):
            policy += ':' + str(legacy['restart']['MaximumRetryCount'])
        self.run(['docker', 'update', '--restart=' + policy, legacy['container']])
        self.run(['docker', 'start', legacy['container']])

    def activate(self, candidate, legacy_container=None, legacy_project='mb-ai-edge'):
        candidate = self.release(candidate)
        with locked(self.root):
            previous = self.current()
            config = read_config(candidate)
            if config.get('tls_enabled', True):
                contract_check(config)
            self.compose(candidate, 'config', '--quiet')
            self.compose(candidate, 'run', '--rm', '--no-deps', 'edge', '-t')
            require(not legacy_container or previous is None, 'Migration requires no current infra Edge')
            legacy = self.legacy_snapshot(legacy_container, legacy_project) if legacy_container else None
            stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
            receipt_path = self.root / 'transactions' / (stamp + '.json')
            receipt = dict(candidate=candidate.name, previous=previous.name if previous else None, legacy=legacy, status='prepared')
            write_json(receipt_path, receipt)
            if legacy:
                backup = self.root / 'transactions' / (stamp + '.tar.gz')
                with tarfile.open(backup, 'w:gz', dereference=False) as archive:
                    archive.add(legacy['directory'], arcname='mb-ai-edge')
                backup.chmod(0o600)
            try:
                if legacy:
                    # Only the explicitly inspected legacy Edge is stopped; no compose down.
                    self.run(['docker', 'update', '--restart=no', legacy['container']])
                    self.run(['docker', 'stop', legacy['container']])
                self.switch(candidate)
                self.compose(candidate, 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '90', 'edge')
                self.verify(candidate, self.run)
                receipt['status'] = 'committed'
                write_json(receipt_path, receipt)
                print('UNCHANGED Edge release:' if previous == candidate else 'PASS Edge release:', candidate.name, 'receipt:', receipt_path.name)
            except Exception as error:
                recovery = []
                try:
                    if previous:
                        self.switch(previous)
                        self.compose(previous, 'up', '-d', '--no-deps', '--wait', '--wait-timeout', '90', 'edge')
                        self.verify(previous, self.run)
                    else:
                        self.compose(candidate, 'stop', 'edge')
                        (self.root / 'current').unlink(missing_ok=True)
                    if legacy:
                        self.restore_legacy(legacy)
                except Exception as restore_error:
                    recovery.append(str(restore_error))
                receipt.update(status='recovery-failed' if recovery else 'reverted', error=str(error), recovery_errors=recovery)
                write_json(receipt_path, receipt)
                raise RuntimeError(f'Deploy failed; {receipt["status"]}; receipt {receipt_path}: {error}; {recovery}') from error

    def legacy_rollback(self, receipt_id):
        require(re.fullmatch(r'[A-Za-z0-9_-]+\.json', receipt_id), 'Invalid receipt ID')
        with locked(self.root):
            path = self.root / 'transactions' / receipt_id
            receipt = json.loads(path.read_text())
            require(receipt.get('legacy') and receipt['status'] == 'committed', 'Receipt is not a committed migration')
            current = self.current()
            require(current is not None, 'No active infra release')
            self.compose(current, 'stop', 'edge')
            try:
                self.restore_legacy(receipt['legacy'])
            except Exception:
                self.compose(current, 'up', '-d', '--no-deps', '--wait', 'edge')
                raise
            (self.root / 'current').unlink()
            receipt['status'] = 'legacy-restored'
            write_json(path, receipt)


def public_bindings(containers):
    failures = []
    for container in containers:
        name = container.get('Name', container['Id'][:12]).lstrip('/')
        labels = container['Config'].get('Labels') or {}
        host_mode = container['HostConfig'].get('NetworkMode') == 'host'
        if host_mode and not (labels.get('com.docker.compose.project') == 'mb-ai-infra' and labels.get('com.docker.compose.service') == 'edge'):
            failures.append(f'{name}: undeclared host networking')
        for port, mappings in container['NetworkSettings'].get('Ports', {}).items():
            for mapping in mappings or []:
                host = mapping.get('HostIp', '')
                if not host or not ipaddress.ip_address(host).is_loopback:
                    failures.append(f"{name}: {host}:{mapping['HostPort']} -> {port}")
    return failures


def security_check(config, runner=run):
    checks = []
    def check(name, operation):
        try:
            operation()
            checks.append(dict(name=name, status='PASS'))
        except Exception as error:
            checks.append(dict(name=name, status='FAIL', detail=str(error)))
    for service in ('docker', 'ssh', 'ufw', 'fail2ban', 'auditd', 'certbot.timer', 'mb-ai-docker-guard'):
        check(service, lambda s=service: require(runner(['systemctl', 'is-active', s]) == 'active', f'{s} is inactive'))
    check('ufw enabled', lambda: require('Status: active' in runner(['ufw', 'status']), 'UFW is not active'))
    check('Docker boot enabled', lambda: require(runner(['systemctl', 'is-enabled', 'docker']) == 'enabled', 'Docker is disabled'))
    def ssh_check():
        effective = dict(line.split(maxsplit=1) for line in runner(['/usr/sbin/sshd', '-T']).splitlines())
        for key in ('passwordauthentication', 'kbdinteractiveauthentication', 'permitrootlogin', 'x11forwarding'):
            require(effective.get(key) == 'no', f'SSH {key} is not disabled')
        require(effective.get('port') == str(config['ssh_port']), 'SSH port differs from inventory')
    check('SSH baseline', ssh_check)
    def docker_check():
        ids = runner(['docker', 'ps', '-q']).split()
        failures = public_bindings(json.loads(runner(['docker', 'inspect', *ids]))) if ids else []
        require(not failures, 'Unexpected Docker exposure: ' + '; '.join(failures))
    check('Docker bindings', docker_check)
    def socket_check():
        failures = []
        for line in runner(['ss', '-H', '-lntu']).splitlines():
            fields = line.split()
            address, port = fields[4].rsplit(':', 1)
            address = address.strip('[]').split('%')[0]
            local = address not in ('*', '') and ipaddress.ip_address(address).is_loopback
            allowed = {config['ssh_port'], 80, 443} if fields[0] == 'tcp' else {68, 546}
            if not local and int(port) not in allowed:
                failures.append(fields[0] + ' ' + fields[4])
        require(not failures, 'Unexpected listeners: ' + '; '.join(failures))
    check('Host listeners IPv4/IPv6', socket_check)
    def baseline_check():
        sysctls = {'net.ipv4.conf.all.accept_redirects': '0', 'net.ipv4.conf.default.accept_redirects': '0',
                   'net.ipv4.conf.all.send_redirects': '0', 'net.ipv4.conf.default.send_redirects': '0',
                   'net.ipv4.conf.all.accept_source_route': '0', 'net.ipv4.conf.default.accept_source_route': '0',
                   'net.ipv6.conf.all.accept_redirects': '0', 'net.ipv6.conf.default.accept_redirects': '0',
                   'net.ipv6.conf.all.accept_source_route': '0', 'net.ipv4.tcp_syncookies': '1',
                   'net.ipv4.icmp_echo_ignore_broadcasts': '1', 'kernel.kptr_restrict': '2', 'kernel.dmesg_restrict': '1',
                   'fs.protected_hardlinks': '1', 'fs.protected_symlinks': '1'}
        for key, expected in sysctls.items():
            require(runner(['sysctl', '-n', key]) == expected, f'{key} differs from baseline')
        audit = runner(['auditctl', '-l'])
        for key in ('mb_ai_ssh', 'mb_ai_policy', 'mb_ai_infra', 'mb_ai_tls', 'mb_ai_sudo'):
            require(key in audit, f'Missing audit rule {key}')
        require('sshd' in runner(['fail2ban-client', 'status']), 'SSH jail is not enabled')
        apt = runner(['apt-config', 'dump'])
        require('APT::Periodic::Unattended-Upgrade "1"' in apt, 'Unattended security updates are disabled')
        require('Unattended-Upgrade::Automatic-Reboot "false"' in apt, 'Automatic reboot policy differs')
    check('Kernel, audit and security update baseline', baseline_check)
    def renewal_check():
        renewal = Path(config['tls_root']) / 'renewal' / (config['domain'] + '.conf')
        text = renewal.read_text()
        require(re.search(r'^authenticator\s*=\s*webroot\s*$', text, re.M), 'Certificate renewal must use webroot')
        root = re.escape(config['acme_root'])
        domain = re.escape(config['domain'])
        require(re.search(r'^webroot_path\s*=\s*' + root + r',?\s*$', text, re.M) or
                re.search(r'^' + domain + r'\s*=\s*' + root + r'\s*$', text, re.M), 'Renewal webroot differs; use tls-adopt')
        hook = Path(config['tls_root']) / 'renewal-hooks/deploy/50-mb-ai-infra'
        require('infra.py reload' in hook.read_text() and os.access(hook, os.X_OK), 'Certificate deploy hook is missing')
    check('Selected certificate renewal contract', renewal_check)
    firewall = Path(__file__).with_name('firewall.py')
    check('Docker IPv4/IPv6 guard', lambda: runner([sys.executable, firewall, 'verify'], input=json.dumps(config)))
    print(json.dumps({'checks': checks, 'result': 'PASS' if all(c['status'] == 'PASS' for c in checks) else 'FAIL'}, indent=2))
    require(all(c['status'] == 'PASS' for c in checks), 'Security verification failed; see report')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['config-check', 'contract-check', 'security-check', 'deploy', 'rollback', 'legacy-rollback', 'smoke', 'reload', 'manifest'])
    parser.add_argument('--release')
    parser.add_argument('--receipt')
    parser.add_argument('--legacy-container')
    parser.add_argument('--legacy-project', default='mb-ai-edge')
    args = parser.parse_args()
    deployment = Deployment()
    if args.action in ('config-check', 'contract-check', 'security-check'):
        config = validate_config(json.load(sys.stdin))
        if args.action == 'contract-check':
            contract_check(config)
        elif args.action == 'security-check':
            security_check(config)
        else:
            print('PASS deployment configuration')
    elif args.action == 'manifest':
        release = Path(args.release)
        require(release.parent == ROOT / 'releases' and release.is_dir() and not release.is_symlink(), 'Manifest path must be an Infra release')
        write_json(release / 'manifest.json', {'version': release.name.split('-')[0],
                   'files': {name: hashlib.sha256((release / name).read_bytes()).hexdigest() for name in RELEASE_FILES}})
    elif args.action in ('deploy', 'rollback'):
        require(args.release, '--release is required')
        deployment.activate(args.release, args.legacy_container, args.legacy_project)
    elif args.action == 'legacy-rollback':
        require(args.receipt, '--receipt is required')
        deployment.legacy_rollback(args.receipt)
    elif args.action == 'smoke':
        smoke_check(deployment.release(args.release) if args.release else deployment.current())
        print('PASS TLS, routes, redirect and ACME mapping')
    elif args.action == 'reload':
        with locked(ROOT):
            current = deployment.current()
            if current and read_config(current).get('tls_enabled', True):
                deployment.compose(current, 'exec', '-T', 'edge', 'nginx', '-t')
                deployment.compose(current, 'exec', '-T', 'edge', 'nginx', '-s', 'reload')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'FAIL {exc}', file=sys.stderr)
        sys.exit(1)
