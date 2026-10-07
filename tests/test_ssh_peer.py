import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ssh_peer', Path(__file__).resolve().parents[1] / 'scripts/ssh_peer.py')
ssh_peer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh_peer)


class SshPeerTests(unittest.TestCase):
    def test_ipv4_ipv6_and_mixed_administrator_networks(self):
        cidrs = ['198.51.100.0/24', '2001:db8::/64']
        self.assertEqual(ssh_peer.validate_connection('198.51.100.10 52001 192.0.2.10 22\n', cidrs), '198.51.100.10')
        self.assertEqual(ssh_peer.validate_connection('2001:db8::10 52001 2001:db8:1::10 2222', cidrs), '2001:db8::10')

    def test_missing_malformed_and_injected_session_records_fail_closed(self):
        for connection in ('', None, '198.51.100.10', '198.51.100.10 52001 192.0.2.10',
                           'banner 198.51.100.10 52001 192.0.2.10 22',
                           'not-an-ip 52001 192.0.2.10 22', '198.51.100.10 52001 not-an-ip 22',
                           '198.51.100.10 0 192.0.2.10 22', '198.51.100.10 52001 192.0.2.10 65536',
                           '198.51.100.10 52001 192.0.2.10 22;id'):
            with self.subTest(connection=connection), self.assertRaises((ValueError, TypeError)):
                ssh_peer.validate_connection(connection, ['198.51.100.10/32'])

    def test_missing_invalid_or_nonmatching_policy_is_rejected(self):
        for cidrs in ([], None, ['192.0.2.0/24'], ['2001:db8::/64'], ['invalid']):
            with self.subTest(cidrs=cidrs), self.assertRaises((ValueError, TypeError)):
                ssh_peer.validate_connection('198.51.100.10 52001 192.0.2.10 22', cidrs)


if __name__ == '__main__':
    unittest.main()
