#!/usr/bin/env bash
# setup.sh — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)
# Installs dependencies and runs smoke tests.
# FR-DEP-001: no credentials in this file.
# FR-DEP-002: --help flags on smoke tests must succeed without ANTHROPIC_API_KEY.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing dependencies from scripts/requirements.txt..."
pip install -r "${SCRIPT_DIR}/requirements.txt"

echo "Smoke test: ns003_critic.py --help..."
python3 "${SCRIPT_DIR}/ns003_critic.py" --help || {
    echo "ERROR: ns003_critic.py --help failed" >&2
    exit 1
}

echo "Smoke test: uca004_runner.py --help..."
python3 "${SCRIPT_DIR}/uca004_runner.py" --help || {
    echo "ERROR: uca004_runner.py --help failed" >&2
    exit 1
}

echo "SETUP OK: all dependencies installed and smoke tests passed."
