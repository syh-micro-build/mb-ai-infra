"""Controller-only dispatch. No shell evaluation and no local Ansible connection."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys


PLAYBOOKS = {
    'preflight': 'preflight', 'check': 'provision',
    'bootstrap-zero': 'bootstrap-zero', 'bootstrap': 'bootstrap',
    'provision': 'provision', 'verify': 'verify',
    'deploy': 'deploy', 'infra-deploy': 'deploy',
    'migrate': 'migrate', 'migrate-verify': 'verify',
    'rollback': 'rollback', 'legacy-rollback': 'legacy-rollback',
    'security-check': 'security-check', 'security-verify': 'security-check',
    'security-apply': 'security', 'tls-bootstrap': 'tls',
    'tls-check': 'tls-check', 'tls-adopt': 'tls-adopt',
}
COMMANDS = set(PLAYBOOKS) | {'init', 'version', 'external-verify'}
SAFE_FLAGS = {'--check', '--diff', '--ask-become-pass', '--ask-vault-pass'}


def invocation(argv):
    if not argv or argv[0] not in COMMANDS:
        raise ValueError('Unknown command. Run ./infra help.')
    command, args = argv[0], list(argv[1:])
    extra = {}
    if command in ('rollback', 'legacy-rollback'):
        value = args.pop(0) if args else ''
        pattern = r'[A-Za-z0-9_.-]+' if command == 'rollback' else r'[A-Za-z0-9_-]+\.json'
        if not re.fullmatch(pattern, value) or value.startswith(('.', '-')):
            raise ValueError('Supply one retained release ID or migration receipt filename, without a path.')
        key = 'infra_rollback_release' if command == 'rollback' else 'infra_migration_receipt'
        extra[key] = value
    if command == 'external-verify':
        if len(args) % 2 or any(args[i] != '--address' for i in range(0, len(args), 2)):
            raise ValueError('external-verify accepts only repeated --address IP options.')
        for value in args[1::2]:
            ipaddress.ip_address(value)
    else:
        if any(arg not in SAFE_FLAGS and not re.fullmatch(r'-v{1,4}', arg) for arg in args):
            raise ValueError('Allowed Ansible options: --check, --diff, --ask-become-pass, --ask-vault-pass, -v to -vvvv.')
        if command in ('init', 'version') and args:
            raise ValueError(f'{command} takes no Ansible options.')
        if command == 'check':
            args = ['--check', '--diff', *args]
    return command, args, extra


def compatible_toolchain(workspace, baked=Path('/opt/runner')):
    for line in (baked / 'toolchain.sha256').read_text().splitlines():
        digest, relative = line.split(None, 1)
        actual = hashlib.sha256((workspace / relative.strip()).read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError('Runner dependencies differ from this checkout. Run ./infra init again (or init --build).')
    if (workspace / 'VERSION').read_text().strip() != (baked / 'VERSION').read_text().strip():
        raise ValueError('Runner version differs from this checkout. Run ./infra init again.')


def inventory_hosts(data):
    def group_hosts(name, seen):
        if name in seen:
            return set()
        seen.add(name)
        group = data.get(name, {})
        result = set(group.get('hosts', []))
        for child in group.get('children', []):
            result |= group_hosts(child, seen)
        return result
    hosts = group_hosts('mb_ai', set())
    if not hosts:
        raise ValueError('Inventory must declare at least one remote host in mb_ai.')
    hostvars = data.get('_meta', {}).get('hostvars', {})
    for host in hosts:
        values = hostvars.get(host, {})
        target = str(values.get('ansible_host', host)).lower().strip('[]')
        if values.get('ansible_connection', 'ssh') != 'ssh':
            raise ValueError('Runner supports SSH managed nodes only; local/container connections are refused.')
        try:
            loopback = ipaddress.ip_address(target).is_loopback
        except ValueError:
            loopback = target in ('localhost', 'localhost.localdomain')
        if loopback:
            raise ValueError('A managed node must be remote; localhost and loopback destinations are refused.')
        user = values.get('ansible_user', '')
        if not isinstance(user, str) or user == 'root' or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
            raise ValueError('Declare a non-root SSH account with sudo as ansible_user.')
        if values.get('ansible_password') or values.get('ansible_ssh_pass'):
            raise ValueError('SSH public-key authentication is required; use Vault for sudo secrets if needed.')
        if values.get('ansible_python_interpreter', '/usr/bin/python3') != '/usr/bin/python3':
            raise ValueError('Managed nodes use the Ubuntu system interpreter /usr/bin/python3.')
    return hosts


def controller_identity(environ):
    """OpenSSH needs a passwd record when Docker uses the operator's arbitrary UID."""
    import pwd
    env = dict(environ)
    try:
        pwd.getpwuid(os.getuid())
    except KeyError:
        directory = Path('/tmp/infra-identity')
        directory.mkdir(mode=0o700, exist_ok=True)
        passwd = Path('/etc/passwd').read_text()
        passwd += f'operator:x:{os.getuid()}:{os.getgid()}:Infra operator:/home/runner:/usr/sbin/nologin\n'
        (directory / 'passwd').write_text(passwd)
        groups = Path('/etc/group').read_text() + f'operator:x:{os.getgid()}:\n'
        (directory / 'group').write_text(groups)
        env.update(LD_PRELOAD='/opt/runner/libnss_wrapper.so',
                   NSS_WRAPPER_PASSWD=str(directory / 'passwd'), NSS_WRAPPER_GROUP=str(directory / 'group'))
    return env


def ssh_environment(environ, ssh_dir=Path('/run/infra-ssh')):
    env = dict(environ)
    known_hosts = ssh_dir / 'known_hosts'
    if not known_hosts.is_file() or not known_hosts.stat().st_size:
        raise ValueError('Supply a nonempty known_hosts file with independently verified server fingerprints.')
    args = ['-F', '/dev/null', '-o', 'ControlMaster=auto', '-o', 'ControlPersist=60s',
            '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={known_hosts}',
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'PreferredAuthentications=publickey',
            '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no']
    identity = ssh_dir / 'identity'
    if identity.is_file():
        if identity.stat().st_mode & 0o077:
            raise ValueError('SSH private key permissions must be 0600 (or stricter) on the control machine.')
        result = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', str(identity)],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if result.returncode:
            raise ValueError('Cannot read this private key. For encrypted keys, load the key into ssh-agent first.')
        env['ANSIBLE_PRIVATE_KEY_FILE'] = str(identity)
        env.pop('SSH_AUTH_SOCK', None)
        args += ['-o', 'IdentitiesOnly=yes']
    elif env.get('SSH_AUTH_SOCK'):
        result = subprocess.run(['ssh-add', '-l'], env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, check=False)
        if result.returncode:
            raise ValueError('SSH agent is unavailable or has no loaded identities.')
    else:
        raise ValueError('Select --ssh-key or load a key into SSH_AUTH_SOCK on the control machine.')
    env['ANSIBLE_SSH_ARGS'] = ' '.join(args)
    env['ANSIBLE_HOST_KEY_CHECKING'] = 'True'
    return env


def playbook_argv(command, flags, extra, inventory, limit):
    argv = ['ansible-playbook', '-i', inventory, '--limit', limit,
            f'ansible/playbooks/{PLAYBOOKS[command]}.yml', *flags]
    if extra:
        argv += ['--extra-vars', json.dumps(extra)]
    return argv


def require_prompt_terminal(flags):
    if {'--ask-become-pass', '--ask-vault-pass'}.intersection(flags):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError('Interactive passwords require terminal stdin and stdout; run directly or use a Vault password file.')


def main(argv):
    command, flags, extra = invocation(argv)
    require_prompt_terminal(flags)
    if command == 'version':
        import ansible.release
        import yaml
        import jinja2
        manifest = Path('/opt/runner/collections/ansible_collections/community/general/MANIFEST.json')
        print(json.dumps({'infra': Path('/opt/runner/VERSION').read_text().strip(),
                          'python': sys.version.split()[0], 'ansible': ansible.release.__version__,
                          'PyYAML': yaml.__version__, 'Jinja2': jinja2.__version__,
                          'community.general': json.loads(manifest.read_text())['collection_info']['version']}, indent=2))
        return
    workspace = Path('/workspace')
    compatible_toolchain(workspace)
    os.chdir(workspace)
    if command == 'external-verify':
        site = os.environ['INFRA_SITE']
        os.execvp('python3', ['python3', 'scripts/probe.py', '--site', site,
                             '--report', '/reports/external.json', *flags])
    env = ssh_environment(controller_identity(os.environ))
    inventory = env['INFRA_INVENTORY']
    limit = env.get('INFRA_LIMIT', 'mb_ai')
    vault_flags = ['--ask-vault-pass'] if '--ask-vault-pass' in flags else []
    result = subprocess.run(['ansible-inventory', '-i', inventory, '--list', *vault_flags], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode:
        # Inventory output can contain decrypted secrets; never echo it.
        raise ValueError('Inventory could not be read. Check its format and Vault password configuration.')
    inventory_hosts(json.loads(result.stdout))
    selected = subprocess.run(['ansible-playbook', '-i', inventory, '--limit', limit,
                               f'ansible/playbooks/{PLAYBOOKS.get(command, "provision")}.yml',
                               '--list-hosts', *vault_flags], env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if selected.returncode or not any(int(count) for count in re.findall(r'hosts \((\d+)\):', selected.stdout)):
        raise ValueError('The inventory/limit selects no mb_ai hosts, or the playbook could not be loaded.')
    for directory in ('/tmp/ansible/local', '/tmp/ansible/cp'):
        Path(directory).mkdir(parents=True, exist_ok=True, mode=0o700)
    if command == 'init':
        result = subprocess.run(['ansible-playbook', '-i', inventory,
                                 'ansible/playbooks/provision.yml', '--syntax-check'], env=env, check=False)
        if result.returncode:
            raise ValueError('Provision syntax validation failed.')
        print('READY: Runner, inventory and local SSH credentials validated. No target was contacted.')
        return
    os.execvpe('ansible-playbook', playbook_argv(command, flags, extra, inventory, limit), env)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f'[BLOCKED] {error}', file=sys.stderr)
        sys.exit(2)
