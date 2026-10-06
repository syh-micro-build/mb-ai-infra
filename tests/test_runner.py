import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runner_dispatch', REPO / 'runner/dispatch.py')
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


def inventory():
    return {'mb_ai': {'children': ['edge']}, 'edge': {'hosts': ['edge01']},
            '_meta': {'hostvars': {'edge01': {'ansible_host': '192.0.2.10', 'ansible_user': 'deploy'}}}}


class DispatchTests(unittest.TestCase):
    def test_named_recovery_uses_json_argument_without_evaluation(self):
        command, flags, extra = dispatch.invocation(['rollback', '1.0.0-retained', '--check'])
        argv = dispatch.playbook_argv(command, flags, extra, '/run/inventory/hosts.yml', 'edge01')
        self.assertIn('--check', argv)
        self.assertEqual(json.loads(argv[-1]), {'infra_rollback_release': '1.0.0-retained'})
        for value in ('../other', 'id;whoami', '$(id)', '.', '--check'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dispatch.invocation(['rollback', value])
        with self.assertRaises(ValueError):
            dispatch.invocation(['legacy-rollback', 'receipt.txt'])

    def test_plan_is_always_check_and_diff_and_unknown_flags_fail(self):
        command, flags, extra = dispatch.invocation(['check'])
        self.assertEqual(flags, ['--check', '--diff'])
        self.assertEqual(dispatch.PLAYBOOKS[command], 'provision')
        for args in (['provision', '--connection', 'local'], ['verify', '-e', 'foo=bar'],
                     ['init', '--check'], ['not-a-command']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                dispatch.invocation(args)

    def test_external_probe_cannot_override_report_or_site(self):
        self.assertEqual(dispatch.invocation(['external-verify', '--address', '2001:db8::10'])[1],
                         ['--address', '2001:db8::10'])
        for args in (['--site', '/secret'], ['--report', '/tmp/report'], ['--address'], ['--address', 'bad']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                dispatch.invocation(['external-verify', *args])

    def test_remote_inventory_nested_groups_and_fail_closed_boundaries(self):
        self.assertEqual(dispatch.inventory_hosts(inventory()), {'edge01'})
        for key, value in (('ansible_connection', 'local'), ('ansible_connection', 'docker'),
                           ('ansible_host', '127.0.0.2'), ('ansible_host', '::1'),
                           ('ansible_host', 'localhost'), ('ansible_user', 'root'), ('ansible_user', 1000),
                           ('ansible_password', 'secret'), ('ansible_python_interpreter', '/opt/app/python')):
            data = copy.deepcopy(inventory())
            data['_meta']['hostvars']['edge01'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                dispatch.inventory_hosts(data)
        with self.assertRaises(ValueError):
            dispatch.inventory_hosts({'mb_ai': {'hosts': []}})

    def test_dependency_mismatch_blocks_stale_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace, baked = root / 'workspace', root / 'baked'
            for path in (workspace, baked):
                path.mkdir()
                (path / 'VERSION').write_text('1.0.0\n')
            (workspace / 'requirements-runner.txt').write_text('original')
            digest = hashlib.sha256(b'original').hexdigest()
            (baked / 'toolchain.sha256').write_text(f'{digest}  requirements-runner.txt\n')
            dispatch.compatible_toolchain(workspace, baked)
            (workspace / 'requirements-runner.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'dependencies differ'):
                dispatch.compatible_toolchain(workspace, baked)

    def test_known_hosts_and_loaded_agent_are_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'known_hosts'):
                dispatch.ssh_environment({}, ssh_dir)
            (ssh_dir / 'known_hosts').write_text('verified-host-key')
            with self.assertRaisesRegex(ValueError, 'Select --ssh-key'):
                dispatch.ssh_environment({}, ssh_dir)
            with patch.object(dispatch.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                env = dispatch.ssh_environment({'SSH_AUTH_SOCK': '/run/agent'}, ssh_dir)
            self.assertIn('StrictHostKeyChecking=yes', env['ANSIBLE_SSH_ARGS'])
            self.assertIn('PasswordAuthentication=no', env['ANSIBLE_SSH_ARGS'])
            with patch.object(dispatch.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
                with self.assertRaisesRegex(ValueError, 'no loaded identities'):
                    dispatch.ssh_environment({'SSH_AUTH_SOCK': '/run/agent'}, ssh_dir)


@unittest.skipIf(sys.platform == 'win32', 'Bash/Docker CLI contracts exercised on Linux CI')
class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repo with spaces'
        self.root.mkdir()
        shutil.copy(REPO / 'infra', self.root / 'infra')
        (self.root / 'infra').chmod(0o755)
        (self.root / 'hosts.yml').write_text('fixture inventory')
        (self.root / 'known hosts').write_text('verified key')
        (self.root / 'private key').write_text('fixture key')
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        fake = bin_dir / 'docker'
        fake.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['CAPTURE'], 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['image', 'inspect'] and '--format' in sys.argv:
    print('sha256:' + 'a' * 64)
if sys.argv[1] == 'run':
    sys.exit(int(os.environ.get('RUN_EXIT', '0')))
''')
        fake.chmod(0o755)
        self.capture = self.root / 'calls.jsonl'
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', CAPTURE=str(self.capture),
                        INFRA_RUNNER_IMAGE='test:image', INFRA_INVENTORY=str(self.root / 'hosts.yml'),
                        INFRA_KNOWN_HOSTS=str(self.root / 'known hosts'), INFRA_SSH_KEY=str(self.root / 'private key'))
        self.env.pop('INFRA_DOCKER_NETWORK', None)
        self.env.pop('INFRA_VAULT_PASSWORD_FILE', None)
        self.env.pop('INFRA_REPORTS_DIR', None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(['bash', str(self.root / 'infra'), *args], env=self.env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def calls(self):
        return [json.loads(line) for line in self.capture.read_text().splitlines()]

    def test_mounts_credentials_read_only_without_host_privilege(self):
        result = self.run_cli('rollback', 'retained-id', '--diff')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.calls()[-1]
        self.assertEqual(run[-3:], ['rollback', 'retained-id', '--diff'])
        for dst in ('/workspace', '/run/inventory', '/run/infra-ssh/identity', '/run/infra-ssh/known_hosts'):
            self.assertTrue(any(f'dst={dst},readonly' in arg for arg in run))
        self.assertIn('--read-only', run)
        self.assertNotIn('--privileged', run)
        self.assertFalse(any('docker.sock' in arg for arg in run))
        self.assertIn('sha256:' + 'a' * 64, run)

    def test_invalid_command_or_missing_credentials_never_runs_a_container(self):
        result = self.run_cli('typo')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.capture.exists())
        (self.root / 'known hosts').unlink()
        result = self.run_cli('preflight')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(any(call[0] in ('run', 'pull') for call in self.calls()))

    def test_failed_operation_propagates_and_does_not_pin_failed_init(self):
        self.env['RUN_EXIT'] = '7'
        result = self.run_cli('init')
        self.assertEqual(result.returncode, 7)
        self.assertFalse((self.root / '.cache/runner-image').exists())

    def test_init_reuses_a_local_image_without_a_registry_pull(self):
        result = self.run_cli('init')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] == 'pull' for call in self.calls()))
        self.assertIn('sha256:' + 'a' * 64, (self.root / '.cache/runner-image').read_text())

    def test_external_verification_does_not_mount_ssh_credentials(self):
        result = self.run_cli('external-verify', '--address', '203.0.113.10')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = self.calls()[-1]
        self.assertFalse(any('/run/infra-ssh/' in arg for arg in run))


if __name__ == '__main__':
    unittest.main()
