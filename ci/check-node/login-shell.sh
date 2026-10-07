#!/usr/bin/env bash
# Negative tests alter the session environment at the SSH login boundary only.
set -euo pipefail
if [[ -r /run/test-peer-mode ]]; then
  case "$(cat /run/test-peer-mode)" in
    missing) unset SSH_CONNECTION ;;
    malformed) export SSH_CONNECTION='invalid-session-record' ;;
    *) echo 'Invalid test peer mode' >&2; exit 2 ;;
  esac
fi
exec /bin/bash "$@"
