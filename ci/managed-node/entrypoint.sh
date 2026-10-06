#!/usr/bin/env bash
set -euo pipefail
mkdir -p /home/deploy/.ssh
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
exec /usr/sbin/sshd -D -e
