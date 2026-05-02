#!/usr/bin/env bash
set -euo pipefail
. "$(cd "$(dirname -- "$0")" && pwd)/python-detect.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <command...>" >&2
  exit 64
fi

start="$($PYTHON -c 'import time; print(int(time.time()*1000))')"
"$@"
end="$($PYTHON -c 'import time; print(int(time.time()*1000))')"
elapsed=$((end - start))
printf 'ELAPSED_MS=%s\n' "$elapsed"
