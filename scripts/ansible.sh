#!/usr/bin/env bash
set -euo pipefail
inventory="${INVENTORY:-ansible/inventory/local/hosts.yml}"
limit="${LIMIT:-mb_ai}"
playbook="${1:?playbook required}"
shift
if [[ ! -f "$inventory" ]]; then
  echo "Inventory missing: $inventory. Copy ansible/inventory/example/ to ansible/inventory/local/ and fill real host values." >&2
  exit 2
fi
exec ansible-playbook -i "$inventory" --limit "$limit" "ansible/playbooks/$playbook.yml" "$@"
