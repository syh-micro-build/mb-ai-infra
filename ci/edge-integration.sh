#!/usr/bin/env bash
set -euo pipefail
[[ -z "$(docker ps -aq --filter label=com.docker.compose.project=mb-ai-infra)" ]] || { echo 'Refusing to run integration tests against an existing Infra project'; exit 2; }
test_root="$(mktemp -d /tmp/mb-ai-infra-ci.XXXXXX)"
fixture_pid=''
cleanup() {
  docker compose -p mb-ai-infra -f "$test_root/tls/compose.yaml" down 2>/dev/null || true
  [[ -z "$fixture_pid" ]] || kill "$fixture_pid" 2>/dev/null || true
  rm -rf -- "$test_root"
}
trap cleanup EXIT
mkdir -p "$test_root/certs/live/test.example.com" "$test_root/acme/.well-known/acme-challenge"
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj /CN=test.example.com \
  -addext subjectAltName=DNS:test.example.com -keyout "$test_root/certs/live/test.example.com/privkey.pem" \
  -out "$test_root/certs/live/test.example.com/fullchain.pem"
python3 - "$test_root" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
site = {'infra_site': {'domain': 'test.example.com', 'public_interfaces': ['eth0'], 'admin_cidrs': ['192.0.2.1/32'],
                       'tls_root': str(root / 'certs'), 'acme_root': str(root / 'acme'), 'certificate_min_days': 0}}
(root / 'site.json').write_text(json.dumps(site))
PY
python3 scripts/render.py --site "$test_root/site.json" --output "$test_root/http" --http-only
python3 scripts/render.py --site "$test_root/site.json" --output "$test_root/tls"
for mode in http tls; do
  docker compose -p mb-ai-infra -f "$test_root/$mode/compose.yaml" config --quiet
  docker compose -p mb-ai-infra -f "$test_root/$mode/compose.yaml" run --rm --no-deps edge -t
done
docker compose -p mb-ai-infra -f "$test_root/http/compose.yaml" up -d --wait --wait-timeout 90
[[ "$(curl --noproxy '*' -sS --resolve test.example.com:80:127.0.0.1 -o /dev/null -w '%{http_code}' http://test.example.com/)" == 503 ]]
python3 ci/fixture.py > "$test_root/fixture.log" 2>&1 &
fixture_pid=$!
docker compose -p mb-ai-infra -f "$test_root/tls/compose.yaml" up -d --wait --wait-timeout 90
export TEST_CERT="$test_root/certs/live/test.example.com/fullchain.pem"
export CURL_CA_BUNDLE="$TEST_CERT"
PYTHONPATH=scripts python3 - "$test_root/tls" <<'PY'
import sys
from pathlib import Path
from infra import smoke_check
smoke_check(Path(sys.argv[1]))
PY
python3 ci/edge-client.py
docker compose -p mb-ai-infra -f "$test_root/tls/compose.yaml" restart edge
docker compose -p mb-ai-infra -f "$test_root/tls/compose.yaml" up -d --wait --wait-timeout 90
python3 ci/edge-client.py
