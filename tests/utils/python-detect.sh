#!/usr/bin/env sh
# Detect the Python interpreter that is functional on this machine.
# Source this file to get a PYTHON variable pointing to a working python3.
# Tries absolute Homebrew paths first to bypass broken venv shims on PATH.
#
# Usage: . "$(cd "$(dirname "$0")/.." && pwd)/utils/python-detect.sh"

PYTHON=""
for _py_candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 python3.12 python3 python; do
  if { [ -x "$_py_candidate" ] || command -v "$_py_candidate" > /dev/null 2>&1; } && \
     "$_py_candidate" -c "import sys; sys.exit(0)" > /dev/null 2>&1; then
    PYTHON="$_py_candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "ERROR: No working Python interpreter found. Tried: /opt/homebrew/bin/python3.12, python3.12, python3, python" >&2
  exit 1
fi

unset _py_candidate
