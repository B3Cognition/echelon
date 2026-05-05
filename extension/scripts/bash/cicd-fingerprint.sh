#!/usr/bin/env bash
# cicd-fingerprint.sh — fingerprint project files that affect CI/CD config
# Usage: --check | --update | --compute
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel)
FINGERPRINT_FILE="${PROJECT_ROOT}/.specify/squad/cicd-fingerprint.json"

_compute_hash() {
  # Find all CI/CD-relevant files, sort for determinism, hash contents
  {
    find "${PROJECT_ROOT}" \
      -not -path "*/.specify/*" \
      -not -path "*/node_modules/*" \
      -not -path "*/.git/*" \
      \( \
        -name "Dockerfile*" \
        -o -name "package.json" \
        -o -name "pnpm-lock.yaml" \
        -o -name "package-lock.json" \
        -o -name "yarn.lock" \
        -o -name "bun.lockb" \
        -o -name "pyproject.toml" \
        -o -name "requirements.txt" \
        -o -name "setup.py" \
        -o -name "Pipfile" \
        -o -name "Pipfile.lock" \
        -o -name "go.mod" \
        -o -name "go.sum" \
        -o -name "Cargo.toml" \
        -o -name "Cargo.lock" \
        -o -name "Gemfile" \
        -o -name "Gemfile.lock" \
        -o -name "mix.exs" \
        -o -name "mix.lock" \
        -o -name "pom.xml" \
        -o -name "build.gradle" \
        -o -name "build.gradle.kts" \
        -o -name "echelon-config.yml" \
      \) \
      -type f | sort | while read -r f; do
        echo "=== $f ==="
        cat "$f"
      done
  } | sha256sum | awk '{print $1}'
}

case "${1:-}" in
  --compute)
    _compute_hash
    ;;

  --check)
    CURRENT=$(_compute_hash)
    if [ ! -f "${FINGERPRINT_FILE}" ]; then
      echo "cicd-fingerprint: no fingerprint stored — CI/CD config not yet generated" >&2
      exit 1
    fi
    STORED=$(python3 -c "import json; print(json.load(open('${FINGERPRINT_FILE}'))['hash'])" 2>/dev/null || echo "")
    if [ -z "${STORED}" ]; then
      echo "cicd-fingerprint: fingerprint file unreadable" >&2
      exit 1
    fi
    if [ "${CURRENT}" != "${STORED}" ]; then
      echo "cicd-fingerprint: project changed since last echelon.cicd run (hash mismatch)" >&2
      exit 1
    fi
    echo "cicd-fingerprint: up to date (${CURRENT:0:12}...)"
    exit 0
    ;;

  --update)
    CURRENT=$(_compute_hash)
    mkdir -p "$(dirname "${FINGERPRINT_FILE}")"
    python3 - <<PYEOF
import json, datetime, os

data = {
    "hash": "${CURRENT}",
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
}
with open("${FINGERPRINT_FILE}", "w") as f:
    json.dump(data, f, indent=2)
print(f"cicd-fingerprint: stored {data['hash'][:12]}... at ${FINGERPRINT_FILE}")
PYEOF
    ;;

  *)
    echo "Usage: cicd-fingerprint.sh --check | --update | --compute" >&2
    exit 1
    ;;
esac
