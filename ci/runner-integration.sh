#!/usr/bin/env bash
set -euo pipefail
runner="${1:-mb-ai-infra-runner:test}"
sudo_mode="${2:-nopasswd}"
[[ "$sudo_mode" == nopasswd || "$sudo_mode" == password ]]
node_env=()
if [[ "$sudo_mode" == password ]]; then
  TEST_SUDO_PASSWORD="$(openssl rand -hex 24)"
  export TEST_SUDO_PASSWORD
  echo "::add-mask::$TEST_SUDO_PASSWORD"
  node_env+=(--env TEST_SUDO_PASSWORD)
fi
run_infra() {
  if [[ "$sudo_mode" == password ]]; then
    python3 ci/ask-become.py ./infra "$@" --ask-become-pass
  else
    ./infra "$@"
  fi
}
scratch="$(mktemp -d)"
chmod 0755 "$scratch"
prefix="mb-ai-runner-test-$$"
network="$prefix"
nodes=()
agent_pid=''
cleanup() {
  if [[ -n "$agent_pid" ]]; then kill "$agent_pid" || true; fi
  for node in "${nodes[@]}"; do docker rm -f "$node" >/dev/null || true; done
  docker network rm "$network" >/dev/null || true
  rm -rf -- "$scratch"
}
trap cleanup EXIT
docker network create "$network" >/dev/null
ssh-keygen -q -t ed25519 -N '' -f "$scratch/identity"
chmod 0600 "$scratch/identity"
chmod 0644 "$scratch/identity.pub"
export INFRA_RUNNER_IMAGE="$runner" INFRA_SSH_KEY="$scratch/identity"
export INFRA_KNOWN_HOSTS="$scratch/known_hosts" INFRA_REPORTS_DIR="$scratch/reports"
export INFRA_DOCKER_NETWORK="$network"
for version in 22 24; do
  case "$version" in
    22) base=ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401 ;;
    24) base=ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 ;;
  esac
  node="$prefix-$version"
  nodes+=("$node")
  docker build --build-arg "UBUNTU_IMAGE=$base" -t "$node" ci/managed-node
  docker run -d --name "$node" --network "$network" --network-alias "node$version" \
    --mount "type=bind,src=$scratch,dst=/keys,readonly" "${node_env[@]}" "$node" >/dev/null
  ready=false
  for ((attempt=0; attempt<30; attempt++)); do
    if docker exec "$node" test -s /run/sshd.pid; then ready=true; break; fi
    sleep 1
  done
  [[ "$ready" == true ]]
  # Host fingerprint is read through Docker's local test control channel, not trusted on first SSH use.
  printf 'node%s %s\n' "$version" "$(docker exec "$node" ssh-keygen -y -f /etc/ssh/ssh_host_ed25519_key)" >> "$scratch/known_hosts"
  mkdir -p "$scratch/inventory/group_vars"
  cat > "$scratch/inventory/hosts.yml" <<YAML
all:
  children:
    mb_ai:
      hosts:
        edge01:
          ansible_host: node$version
          ansible_user: deploy
          ansible_connection: ssh
          ansible_python_interpreter: /usr/bin/python3
YAML
  cp ansible/inventory/example/group_vars/mb_ai.yml "$scratch/inventory/group_vars/mb_ai.yml"
  export INFRA_INVENTORY="$scratch/inventory/hosts.yml"
  docker exec "$node" sh -c 'test ! -x /usr/bin/python3'
  ./infra init
  printf 'node%s %s\n' "$version" "$(cat "$scratch/identity.pub")" > "$scratch/wrong-known-hosts"
  if run_infra bootstrap-zero --known-hosts "$scratch/wrong-known-hosts" > "$scratch/host-key.log" 2>&1; then
    echo 'A mismatched host key was accepted' >&2; exit 1
  fi
  grep -q 'Host key verification failed' "$scratch/host-key.log"
  if run_infra bootstrap-zero --limit missing-host > "$scratch/limit.log" 2>&1; then
    echo 'An empty host selection was accepted' >&2; exit 1
  fi
  grep -q 'selects no mb_ai hosts' "$scratch/limit.log"
  docker exec "$node" sh -c 'test ! -x /usr/bin/python3'
  if run_infra preflight > "$scratch/preflight.log" 2>&1; then
    echo 'Preflight incorrectly passed without Python' >&2; exit 1
  fi
  cat "$scratch/preflight.log"
  grep -q 'System Python is missing' "$scratch/preflight.log"
  if run_infra bootstrap-zero --check > "$scratch/check.log" 2>&1; then
    echo 'Check mode incorrectly claimed readiness without Python' >&2; exit 1
  fi
  grep -q 'System Python is missing' "$scratch/check.log"
  docker exec "$node" sh -c 'test ! -x /usr/bin/python3'
  if [[ "$version" == 22 ]]; then
    docker exec "$node" cp /etc/os-release /tmp/original-os
    docker exec "$node" sed -i 's/^ID=.*/ID=debian/' /etc/os-release
    if run_infra bootstrap-zero > "$scratch/unsupported.log" 2>&1; then
      echo 'Unsupported OS was accepted' >&2; exit 1
    fi
    grep -q 'Only Ubuntu' "$scratch/unsupported.log"
    docker exec "$node" sh -c 'test ! -x /usr/bin/python3; cp /tmp/original-os /etc/os-release'
  fi
  run_infra bootstrap-zero
  docker exec "$node" /usr/bin/python3 -c 'import apt,sys; assert sys.version_info >= (3, 9)'
  run_infra bootstrap-zero | tee "$scratch/repeat.log"
  grep -Eq 'changed=0 .*failed=0' "$scratch/repeat.log"
  for package in ansible ansible-core python3-pip python3-venv make gcc git; do
    state="$(docker exec "$node" dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)"
    [[ "$state" != installed ]] || { echo "Unexpected managed-node toolchain: $package" >&2; exit 1; }
  done
  docker exec "$node" sh -c 'test "$(cat /opt/sub2api/sentinel)" = application-owned; test "$(cat /opt/mb-ai-docs/sentinel)" = application-owned'
done
# Exercise the alternative authentication route through an actual forwarded Unix agent socket.
eval "$(ssh-agent -s)" >/dev/null
agent_pid="$SSH_AGENT_PID"
ssh-add "$scratch/identity"
INFRA_SSH_KEY='' run_infra bootstrap-zero | tee "$scratch/agent.log"
grep -Eq 'changed=0 .*failed=0' "$scratch/agent.log"
echo "PASS: SSH bootstrap on Ubuntu 22.04/24.04 with $sudo_mode sudo, read-only checks, idempotence, agent and application boundaries."
