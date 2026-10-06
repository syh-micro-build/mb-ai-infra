import contextlib
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import infra
import firewall
from render import load_config, render, REPO
from probe import probe


def fixture_config():
    return load_config(REPO / 'ansible/inventory/example/group_vars/mb_ai.yml')


class ConfigurationTests(unittest.TestCase):
    def test_valid_contracts(self):
        self.assertEqual(fixture_config()['contracts'][0]['name'], 'sub2api')

    def test_nginx_input_injection_rejected(self):
        for key, value in [('domain', 'ok.example.com; return 200;'), ('client_max_body_size', '64m; foo'),
                           ('nginx_image', 'nginx:latest'), ('public_interfaces', ['eth0 -j ACCEPT'])]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                infra.validate_config(dict(fixture_config(), **{key: value}))

    def test_public_or_duplicate_upstream_rejected(self):
        for key, value in [('host', '0.0.0.0'), ('port', 443), ('port', 8081)]:
            config = fixture_config()
            config['contracts'][0]['upstream'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                infra.validate_config(config)

    def test_protected_application_paths(self):
        for path in ('/opt/sub2api', '/opt/sub2api/data', '/opt/mb-ai-docs', '/opt/mb-ai-docs/site', '/tmp/../opt/sub2api'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                infra.safe_path(path)

    def test_docs_prefix_and_stream_settings(self):
        rendered = render(fixture_config(), '/opt/mb-ai-infra/releases/test')
        site = rendered['nginx/conf.d/site.conf']
        self.assertIn('proxy_pass http://docs_backend;', site)
        self.assertNotIn('proxy_pass http://docs_backend/;', site)
        self.assertIn('proxy_buffering off;', site)
        self.assertIn('proxy_request_buffering off;', site)
        self.assertIn('proxy_next_upstream off;', rendered['nginx/conf.d/proxy.inc'])
        self.assertIn('X-Forwarded-For $remote_addr;', rendered['nginx/conf.d/proxy.inc'])

    def test_http_bootstrap_has_no_tls_or_application_proxy(self):
        rendered = render(fixture_config(), '/opt/mb-ai-infra/releases/http', tls=False)
        site = rendered['nginx/conf.d/site.conf']
        self.assertNotIn('ssl_certificate', site)
        self.assertNotIn('proxy_pass', site)
        self.assertIn('return 503', site)
        self.assertIn('acme-challenge', site)

    def test_firewall_matches_original_published_port(self):
        rules = firewall.rules(fixture_config())
        self.assertTrue(any('--ctorigdstport' in rule for rule in rules))
        self.assertFalse(any('--dport' in rule for rule in rules))
        self.assertTrue(any('-j' in rule and rule[-1] == 'DROP' for rule in rules))

    def test_host_rules_separate_ipv4_ipv6_admins(self):
        config = fixture_config()
        v4 = str(firewall.host_rules(config, 4))
        v6 = str(firewall.host_rules(config, 6))
        self.assertIn('198.51.100.10/32', v4)
        self.assertNotIn('2001:db8', v4)
        self.assertIn('2001:db8::10/128', v6)
        self.assertNotIn('198.51.100', v6)


@unittest.skipIf(sys.platform == 'win32', 'Linux runtime requires fcntl and directory symlinks; exercised in Ubuntu CI')
class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = []
        self.runtime = infra.Deployment(self.root, runner=self.runner, verifier=lambda *args: None)
        self.contract = patch('infra.contract_check', lambda config: None)
        self.contract.start()

    def tearDown(self):
        self.contract.stop()
        self.tmp.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append([str(x) for x in argv])
        return ''

    def candidate(self, name):
        path = self.root / 'releases' / name
        for file, body in render(fixture_config(), path.as_posix()).items():
            target = path / file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding='utf-8', newline='\n')
        return path

    def test_success_changes_only_infra_project(self):
        candidate = self.candidate('new')
        self.runtime.activate(candidate)
        self.assertEqual(self.runtime.current(), candidate)
        for call in self.calls:
            self.assertIn('mb-ai-infra', call)
            self.assertNotIn('down', call)
        self.assertEqual(json.loads(next((self.root / 'transactions').glob('*.json')).read_text())['status'], 'committed')

    def test_failed_candidate_restores_previous(self):
        previous = self.candidate('previous')
        candidate = self.candidate('failed')
        self.runtime.switch(previous)
        def verifier(release, runner):
            if release == candidate:
                raise RuntimeError('HTTPS probe failed')
        self.runtime.verify = verifier
        with self.assertRaisesRegex(RuntimeError, 'reverted'):
            self.runtime.activate(candidate)
        self.assertEqual(self.runtime.current(), previous)
        self.assertTrue(any(str(previous / 'compose.yaml') in call and 'up' in call for call in self.calls))

    def test_initial_failure_stops_only_edge_and_unlinks_current(self):
        candidate = self.candidate('failed')
        self.runtime.verify = lambda *args: (_ for _ in ()).throw(RuntimeError('not healthy'))
        with self.assertRaisesRegex(RuntimeError, 'reverted'):
            self.runtime.activate(candidate)
        self.assertFalse((self.root / 'current').exists())
        self.assertTrue(any(call[-2:] == ['stop', 'edge'] for call in self.calls))

    def test_configuration_failure_does_not_switch(self):
        previous = self.candidate('previous')
        candidate = self.candidate('bad-config')
        self.runtime.switch(previous)
        def broken(argv, **kwargs):
            if '-t' in argv:
                raise RuntimeError('nginx -t failed')
            return self.runner(argv)
        self.runtime.run = broken
        with self.assertRaises(RuntimeError):
            self.runtime.activate(candidate)
        self.assertEqual(self.runtime.current(), previous)

    def test_corrupt_release_refused_before_docker(self):
        candidate = self.candidate('corrupt')
        (candidate / 'nginx/conf.d/site.conf').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.runtime.activate(candidate)
        self.assertFalse(self.calls)

    def test_outside_release_refused(self):
        with self.assertRaises(ValueError):
            self.runtime.release('/opt/sub2api')

    def test_legacy_application_container_refused(self):
        container = {'Id': 'abc', 'Config': {'Image': 'nginx:alpine', 'Labels': {'com.docker.compose.project': 'mb-ai-docs'}},
                     'State': {'Running': True}, 'HostConfig': {'RestartPolicy': {'Name': 'always'}}}
        self.runtime.run = lambda *args: json.dumps([container])
        with self.assertRaisesRegex(ValueError, 'legacy Edge'):
            self.runtime.legacy_snapshot('docs', 'mb-ai-edge')

    def test_failed_migration_restores_legacy_restart_policy(self):
        candidate = self.candidate('migrate')
        old = self.root / 'legacy'
        old.mkdir()
        (old / 'compose.yaml').write_text('legacy fixture')
        legacy = dict(container='legacy-id', directory=str(old), restart={'Name': 'always'})
        self.runtime.legacy_snapshot = lambda *args: legacy
        self.runtime.verify = lambda *args: (_ for _ in ()).throw(RuntimeError('bad cutover'))
        with self.assertRaisesRegex(RuntimeError, 'reverted'):
            self.runtime.activate(candidate, legacy_container='legacy-id')
        self.assertIn(['docker', 'update', '--restart=always', 'legacy-id'], self.calls)
        self.assertIn(['docker', 'start', 'legacy-id'], self.calls)
        self.assertTrue(list((self.root / 'transactions').glob('*.tar.gz')))


class AuditTests(unittest.TestCase):
    def container(self, ip, network='bridge', project='sub2api'):
        return {'Id': 'id', 'Name': '/fixture', 'Config': {'Labels': {'com.docker.compose.project': project, 'com.docker.compose.service': 'edge'}},
                'HostConfig': {'NetworkMode': network}, 'NetworkSettings': {'Ports': {'8080/tcp': [{'HostIp': ip, 'HostPort': '8080'}]}}}

    def test_wildcard_ipv4_ipv6_and_private_bindings_fail(self):
        for address in ('0.0.0.0', '::', '192.168.1.10', ''):
            self.assertTrue(infra.public_bindings([self.container(address)]))

    def test_loopback_bindings_pass(self):
        for address in ('127.0.0.1', '::1'):
            self.assertFalse(infra.public_bindings([self.container(address)]))

    def test_application_host_mode_is_not_silently_accepted(self):
        self.assertTrue(infra.public_bindings([self.container('127.0.0.1', network='host')]))

    def test_external_network_failure_cannot_claim_closed_ports(self):
        with patch('probe.run', side_effect=RuntimeError('network down')), patch('probe.socket.create_connection') as connect:
            result = probe(fixture_config(), ['192.0.2.10'])
        self.assertEqual(result['result'], 'FAIL')
        self.assertTrue(any(c['status'] == 'BLOCKED' for c in result['checks']))
        connect.assert_not_called()

    def test_external_open_protected_port_fails(self):
        with patch('probe.run', side_effect=['308', '200', '200']), patch('probe.socket.create_connection', return_value=contextlib.nullcontext()):
            result = probe(fixture_config(), ['192.0.2.10'])
        self.assertEqual(result['result'], 'FAIL')
        self.assertTrue(any('Unexpected successful' in c.get('detail', '') for c in result['checks']))


if __name__ == '__main__':
    unittest.main()
