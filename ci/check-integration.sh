#!/usr/bin/env bash
set -Eeuo pipefail
runner="${1:-mb-ai-infra-runner:test}"
version="${2:-22}"
mode="${3:-password}"
case "$version" in
  22) base=ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401 ;;
  24) base=ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 ;;
  *) echo 'Use Ubuntu 22 or 24' >&2; exit 2 ;;
esac
[[ "$mode" == password || "$mode" == nopasswd ]]
scratch="$(mktemp -d)"
chmod 0755 "$scratch"
node="mb-ai-check-$version-$mode-$$"
network="$node"
cleanup() {
  docker rm -f "$node" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf -- "$scratch"
}
trap cleanup EXIT
report_failure() {
  trap - ERR
  for log in "$scratch"/*.log; do
    [[ -f "$log" ]] || continue
    printf 'Failure diagnostics: %s\n' "${log##*/}" >&2
    tail -n 160 "$log" >&2
  done
  docker logs --tail 40 "$node" >&2 || true
}
trap report_failure ERR
docker network create "$network" >/dev/null
subnet="$(docker network inspect --format '{{(index .IPAM.Config 0).Subnet}}' "$network")"
ssh-keygen -q -t ed25519 -N '' -f "$scratch/identity"
chmod 0600 "$scratch/identity"
chmod 0644 "$scratch/identity.pub"
export INFRA_RUNNER_IMAGE="$runner" INFRA_SSH_KEY="$scratch/identity"
export INFRA_KNOWN_HOSTS="$scratch/known_hosts" INFRA_REPORTS_DIR="$scratch/reports" INFRA_DOCKER_NETWORK="$network"
node_env=()
if [[ "$mode" == password ]]; then
  TEST_SUDO_PASSWORD="$(openssl rand -hex 24)"
  export TEST_SUDO_PASSWORD
  echo "::add-mask::$TEST_SUDO_PASSWORD"
  node_env+=(--env TEST_SUDO_PASSWORD)
fi
docker build --build-arg "UBUNTU_IMAGE=$base" -t "$node" ci/check-node
# Only the disposable SSH target needs systemd/nested Docker privileges, never the Runner.
docker run -d --name "$node" --network "$network" --network-alias check-node \
  --privileged --cgroupns host --tmpfs /run --tmpfs /run/lock \
  --mount type=bind,src=/sys/fs/cgroup,dst=/sys/fs/cgroup \
  --mount "type=bind,src=$scratch,dst=/keys,readonly" "${node_env[@]}" "$node" >/dev/null
ready=false
for ((attempt=0; attempt<90; attempt++)); do
  if docker exec "$node" systemctl is-active --quiet ssh docker; then ready=true; break; fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  docker logs "$node"
  docker exec "$node" journalctl -u docker -u ssh --no-pager || true
  exit 1
fi
if [[ "$mode" == password ]] && docker exec --user deploy "$node" sudo -n true 2>/dev/null; then
  echo 'Password test target incorrectly permits passwordless sudo' >&2; exit 1
fi
printf 'check-node %s\n' "$(docker exec "$node" ssh-keygen -y -f /etc/ssh/ssh_host_ed25519_key)" > "$scratch/known_hosts"
mkdir -p "$scratch/inventory/group_vars"
cat > "$scratch/inventory/hosts.yml" <<'YAML'
all:
  children:
    mb_ai:
      hosts:
        edge01:
          ansible_host: check-node
          ansible_user: deploy
          ansible_connection: ssh
          ansible_python_interpreter: /usr/bin/python3
YAML
site() {
  cat > "$scratch/inventory/group_vars/mb_ai.yml" <<YAML
infra_site:
  domain: ai.mbuild.top
  public_interfaces: [eth0]
  admin_cidrs: ['$1']
  ssh_port: 22
infra_certbot_email: ops@example.com
infra_legacy_services: []
YAML
}
site "$subnet"
export INFRA_INVENTORY="$scratch/inventory/hosts.yml"
run_infra() {
  if [[ "$mode" == password ]]; then
    python3 ci/ask-become.py ./infra "$@" --ask-become-pass
  else
    ./infra "$@"
  fi
}
snapshot() { docker exec -i "$node" python3 - < ci/managed-state.py; }
docker cp ci/fixture.py "$node:/run/contract-fixture.py"
docker exec -d "$node" python3 /run/contract-fixture.py
for ((attempt=0; attempt<30; attempt++)); do
  if docker exec "$node" curl --fail --silent http://127.0.0.1:8081/docs/ >/dev/null; then break; fi
  sleep 1
done
docker exec "$node" sh -c 'test ! -e /opt/mb-ai-infra; test ! -e /etc/mb-ai-infra'
./infra init
run_infra preflight > "$scratch/preflight.log"
snapshot > "$scratch/before.json"
for pass in 1 2; do
  run_infra check > "$scratch/check-$pass.log"
  cat "$scratch/check-$pass.log"
  grep -Eq 'edge01[[:space:]]*:.*unreachable=0[[:space:]]+failed=0' "$scratch/check-$pass.log"
  if grep -Eq 'GetPassWarning|Password input may be echoed|does not support when conditional' "$scratch/check-$pass.log"; then
    echo 'An unsafe prompt or unsupported conditional was logged' >&2; exit 1
  fi
  snapshot > "$scratch/after.json"
  diff -u "$scratch/before.json" "$scratch/after.json"
done
# Fail closed before a policy apply: wrong network, absent record, malformed record.
site 192.0.2.1/32
if run_infra security-apply --check > "$scratch/outside.log" 2>&1; then
  echo 'An administrator outside admin_cidrs was accepted' >&2; exit 1
fi
grep -q 'SSH peer is outside admin_cidrs' "$scratch/outside.log"
site "$subnet"
for peer_mode in missing malformed; do
  docker exec "$node" sh -c 'printf "%s\n" "$1" > /run/test-peer-mode' sh "$peer_mode"
  if run_infra security-apply --check > "$scratch/$peer_mode.log" 2>&1; then
    echo "An invalid SSH session was accepted: $peer_mode" >&2; exit 1
  fi
  if [[ "$peer_mode" == missing ]]; then
    grep -q 'SSH_CONNECTION is unavailable' "$scratch/$peer_mode.log"
  else
    grep -q 'SSH_CONNECTION must contain' "$scratch/$peer_mode.log"
  fi
done
docker exec "$node" rm /run/test-peer-mode
snapshot > "$scratch/after.json"
diff -u "$scratch/before.json" "$scratch/after.json"
docker exec "$node" sh -c 'test ! -e /opt/mb-ai-infra; test ! -e /etc/mb-ai-infra'
for package in ansible ansible-core python3-pip python3-venv make gcc git docker-buildx-plugin; do
  state="$(docker exec "$node" dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)"
  [[ "$state" != installed ]] || { echo "Unexpected managed-node toolchain: $package" >&2; exit 1; }
done
echo "PASS: Ubuntu $version, $mode sudo, repeated full check, zero host policy/package/application writes and fail-closed SSH peer checks."
