#!/usr/bin/env bash
set -euo pipefail
if [[ "${PROOF_START_CHILD:-}" != "1" ]]; then
  export PROOF_START_CHILD=1
  exec timeout --signal=TERM --kill-after=15s 1200 /proof/start.sh
fi
python /proof/install_runtime.py
exec /start.sh
