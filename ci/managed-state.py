"""Read-only fixture snapshot of packages, access policy and owned host files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

paths = [
    '/opt/mb-ai-infra', '/etc/mb-ai-infra', '/etc/letsencrypt', '/var/lib/mb-ai-infra',
    '/opt/sub2api', '/opt/mb-ai-docs', '/etc/ssh', '/etc/sudoers', '/etc/sudoers.d',
    '/etc/docker', '/etc/ufw', '/etc/default/ufw', '/etc/fail2ban', '/etc/audit/rules.d',
    '/etc/sysctl.d/60-mb-ai-infra.conf', '/etc/apt/apt.conf.d/52-mb-ai-infra-upgrades',
    '/etc/systemd/system/mb-ai-docker-guard.service', '/etc/systemd/system/docker.service.d',
]
files = {}


def record(path):
    info = path.lstat()
    value = {'mode': info.st_mode, 'uid': info.st_uid, 'gid': info.st_gid}
    if path.is_symlink():
        value['link'] = os.readlink(path)
    elif path.is_file():
        value['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    files[str(path)] = value


for value in paths:
    root = Path(value)
    if not root.exists() and not root.is_symlink():
        files[value] = None
        continue
    record(root)
    if root.is_dir() and not root.is_symlink():
        for parent, directories, filenames in os.walk(root, followlinks=False):
            for name in directories + filenames:
                record(Path(parent) / name)
packages = subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package} ${db:Status-Status}\n'], text=True)
services = {}
for unit in ('ssh', 'docker', 'certbot.timer', 'fail2ban', 'auditd', 'mb-ai-docker-guard'):
    result = subprocess.run(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'UnitFileState'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    services[unit] = result.stdout
rules = {command: subprocess.check_output([command], text=True) for command in ('iptables-save', 'ip6tables-save')}
print(json.dumps({'files': files, 'packages': sorted(packages.splitlines()), 'services': services, 'rules': rules}, sort_keys=True))
