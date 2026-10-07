import os
from pathlib import Path
import secrets
import subprocess
import sys
import unittest

DRIVER = Path(__file__).resolve().parents[1] / 'ci/ask-become.py'


@unittest.skipIf(sys.platform == 'win32', 'PTY password tests run in Linux CI')
class TerminalDriverTests(unittest.TestCase):
    def run_prompt(self, leak=False):
        password = secrets.token_hex(24)
        code = (
            "import getpass,os,sys; assert sys.stdin.isatty() and sys.stdout.isatty(); "
            "p=getpass.getpass('BECOME password: '); assert p==os.environ['TEST_SUDO_PASSWORD']; "
            + ("print(p)" if leak else "print('PASS interactive password fixture')")
        )
        result = subprocess.run([sys.executable, str(DRIVER), sys.executable, '-c', code],
                                env=dict(os.environ, TEST_SUDO_PASSWORD=password), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        return password, result

    def test_real_terminal_getpass_is_exercised_without_secret_output(self):
        password, result = self.run_prompt()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS interactive password fixture', result.stdout)
        self.assertNotIn(password, result.stdout + result.stderr)
        self.assertNotIn('GetPassWarning', result.stdout + result.stderr)

    def test_accidental_secret_output_is_redacted_and_fails_the_test(self):
        password, result = self.run_prompt(leak=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('[REDACTED]', result.stdout)
        self.assertNotIn(password, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
