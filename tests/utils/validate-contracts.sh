#!/usr/bin/env bash
set -euo pipefail

# Validate BUILD/QA split contract files are present and parseable.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTRACT_DIR="$ROOT_DIR/specs/002-build-qa-phase-split/contracts"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "missing contract: $path" >&2
    return 1
  fi
}

parse_yaml() {
  local path="$1"

  if command -v yq >/dev/null 2>&1; then
    yq e '.' "$path" >/dev/null
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY' "$path"
import sys
from pathlib import Path

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")

# Best-effort parse fallback when PyYAML is unavailable.
try:
    import yaml  # type: ignore
except Exception:
    if not text.strip() or ":" not in text:
        raise SystemExit(1)
    raise SystemExit(0)

try:
    yaml.safe_load(text)
except Exception:
    raise SystemExit(1)
PY
    return 0
  fi

  # Last resort structural check if neither yq nor python3 is available.
  [[ -s "$path" ]] && grep -q ':' "$path"
}

main() {
  local failures=0
  local files=(
    "$CONTRACT_DIR/build-qa-handoff.contract.yaml"
    "$CONTRACT_DIR/rework-loop-transition.contract.yaml"
  )

  for file in "${files[@]}"; do
    if ! require_file "$file"; then
      failures=$((failures + 1))
      continue
    fi

    if ! parse_yaml "$file"; then
      echo "invalid yaml: $file" >&2
      failures=$((failures + 1))
      continue
    fi

    echo "ok: $file"
  done

  if (( failures > 0 )); then
    echo "contract validation failed: ${failures} file(s)" >&2
    exit 1
  fi

  echo "contract validation passed"
}

main "$@"
