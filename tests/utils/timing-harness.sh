#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <command...>" >&2
  exit 64
fi

start="$(python3 -c 'import time; print(int(time.time()*1000))')"
"$@"
end="$(python3 -c 'import time; print(int(time.time()*1000))')"
elapsed=$((end - start))
printf 'ELAPSED_MS=%s\n' "$elapsed"
