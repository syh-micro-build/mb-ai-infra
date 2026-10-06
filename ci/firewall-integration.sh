#!/usr/bin/env bash
set -euo pipefail
[[ "$EUID" -eq 0 ]] || { echo 'Run in CI with sudo'; exit 2; }
server="mb-ai-server-$$"
client="mb-ai-client-$$"
app="mb-ai-app-$$"
web_pid=''
ssh_pid=''
test_root="$(mktemp -d /tmp/mb-ai-guard-ci.XXXXXX)"
cleanup() {
  [[ -z "$web_pid" ]] || kill "$web_pid" 2>/dev/null || true
  [[ -z "$ssh_pid" ]] || kill "$ssh_pid" 2>/dev/null || true
  for ns in "$client" "$server" "$app"; do ip netns del "$ns" 2>/dev/null || true; done
  rm -rf -- "$test_root"
}
trap cleanup EXIT
for ns in "$client" "$server" "$app"; do
  ip netns add "$ns"
  ip -n "$ns" link set lo up
done
ip link add wan0 netns "$server" type veth peer name eth0 netns "$client"
ip link add lan0 netns "$server" type veth peer name eth0 netns "$app"
ip -n "$server" addr add 198.18.0.1/24 dev wan0
ip -n "$client" addr add 198.18.0.2/24 dev eth0
ip -n "$client" addr add 198.18.0.3/24 dev eth0
ip -n "$server" addr add 198.19.0.1/24 dev lan0
ip -n "$app" addr add 198.19.0.2/24 dev eth0
ip -n "$server" -6 addr add fd00:1::1/64 dev wan0
ip -n "$client" -6 addr add fd00:1::2/64 dev eth0
ip -n "$client" -6 addr add fd00:1::3/64 dev eth0
ip -n "$server" -6 addr add fd00:2::1/64 dev lan0
ip -n "$app" -6 addr add fd00:2::2/64 dev eth0
ip -n "$server" link set wan0 up
ip -n "$server" link set lan0 up
ip -n "$client" link set eth0 up
ip -n "$app" link set eth0 up
ip -n "$app" route add default via 198.19.0.1
ip -n "$app" -6 route add default via fd00:2::1
ip netns exec "$server" sysctl -qw net.ipv4.ip_forward=1 net.ipv6.conf.all.forwarding=1
ip netns exec "$app" python3 -m http.server 18080 --bind :: --directory "$test_root" > "$test_root/web.log" 2>&1 &
web_pid=$!
ip netns exec "$server" python3 -m http.server 22 --bind :: --directory "$test_root" > "$test_root/ssh.log" 2>&1 &
ssh_pid=$!
for port in 80 8080; do
  ip netns exec "$server" iptables -t nat -A PREROUTING -i wan0 -p tcp --dport "$port" -j DNAT --to-destination 198.19.0.2:18080
  ip netns exec "$server" ip6tables -t nat -A PREROUTING -i wan0 -p tcp --dport "$port" -j DNAT --to-destination '[fd00:2::2]:18080'
done
ip netns exec "$server" iptables -A INPUT -m comment --comment mb-ai-ci-unrelated -j ACCEPT
python3 - "$test_root/config.json" <<'PY'
import json, sys
sys.path.insert(0, 'scripts')
from render import load_config, REPO
config = load_config(REPO / 'ansible/inventory/example/group_vars/mb_ai.yml')
config.update(public_interfaces=['wan0'], admin_cidrs=['198.18.0.2/32', 'fd00:1::2/128'])
open(sys.argv[1], 'w').write(json.dumps(config))
PY
for iteration in 1 2; do
  ip netns exec "$server" python3 scripts/firewall.py apply --config "$test_root/config.json"
  ip netns exec "$server" python3 scripts/firewall.py verify --config "$test_root/config.json"
  ip netns exec "$server" iptables -S > "$test_root/rules-$iteration"
done
cmp "$test_root/rules-1" "$test_root/rules-2"
ip netns exec "$server" iptables -C INPUT -m comment --comment mb-ai-ci-unrelated -j ACCEPT
sleep 2
for address in 198.18.0.1 '[fd00:1::1]'; do
  ip netns exec "$client" curl --noproxy '*' --fail --silent --max-time 5 "http://$address:80/" > /dev/null
  ip netns exec "$client" curl --noproxy '*' --fail --silent --max-time 5 "http://$address:22/" > /dev/null
  if ip netns exec "$client" curl --noproxy '*' --silent --max-time 2 "http://$address:8080/" > /dev/null; then
    echo "FAIL published 8080 reachable over $address" >&2
    exit 1
  fi
done
if ip netns exec "$client" curl --noproxy '*' --silent --max-time 2 --interface 198.18.0.3 http://198.18.0.1:22/ > /dev/null; then
  echo 'FAIL unauthorized IPv4 SSH source' >&2
  exit 1
fi
if ip netns exec "$client" curl --noproxy '*' --silent --max-time 2 --interface fd00:1::3 'http://[fd00:1::1]:22/' > /dev/null; then
  echo 'FAIL unauthorized IPv6 SSH source' >&2
  exit 1
fi
# Simulate hook loss after a daemon restart, then reapply the persisted policy.
ip netns exec "$server" iptables -F DOCKER-USER
ip netns exec "$server" ip6tables -F DOCKER-USER
ip netns exec "$server" python3 scripts/firewall.py apply --config "$test_root/config.json"
ip netns exec "$server" python3 scripts/firewall.py verify --config "$test_root/config.json"
echo 'PASS dual-stack DNAT filtering, administrator CIDRs, repeated apply and hook recovery'
