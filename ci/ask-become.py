"""CI-only terminal driver: exercise getpass without echoing test credentials."""
import errno
import os
import pty
import re
import select
import subprocess
import sys
import termios
import time


def main():
    password = os.environ['TEST_SUDO_PASSWORD'].encode()
    if not password or b'\n' in password or len(sys.argv) < 2:
        raise ValueError('Supply an ephemeral CI password and a command')
    master, slave = pty.openpty()
    process = subprocess.Popen(sys.argv[1:], stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    output = bytearray()
    sent = False
    deadline = time.monotonic() + 600
    try:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('Interactive CI operation timed out')
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not data:
                    break
                output.extend(data)
            if not sent and b'BECOME password:' in output:
                # getpass disables ECHO before printing its prompt; verify that invariant.
                if termios.tcgetattr(slave)[3] & termios.ECHO:
                    raise RuntimeError('Password prompt still has terminal echo enabled')
                os.write(master, password + b'\n')
                sent = True
            if process.poll() is not None and not ready:
                break
        result = process.wait(timeout=10)
        leaked = password in output
        log = bytes(output).replace(password, b'[REDACTED]')
        # PTY output has Ansible color codes; normalize only the captured CI log.
        log = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', log)
        sys.stdout.buffer.write(log)
        if leaked or (result == 0 and not sent):
            raise RuntimeError('Password prompt was not exercised safely')
        return result
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        os.close(slave)


if __name__ == '__main__':
    sys.exit(main())
