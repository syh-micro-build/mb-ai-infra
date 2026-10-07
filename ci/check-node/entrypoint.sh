#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${TEST_SUDO_PASSWORD:-}" ]]; then
  printf 'deploy:%s\n' "$TEST_SUDO_PASSWORD" | chpasswd
  printf 'deploy ALL=(ALL) ALL\n' > /etc/sudoers.d/deploy
  chmod 0440 /etc/sudoers.d/deploy
fi
mkdir -p /home/deploy/.ssh /run/sshd
cp /keys/identity.pub /home/deploy/.ssh/authorized_keys
chmod 0700 /home/deploy/.ssh
chmod 0600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
ssh-keygen -A
cat > /etc/ssh/sshd_config.d/00-test.conf <<'CONFIG'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
UsePAM yes
CONFIG
exec /sbin/init
