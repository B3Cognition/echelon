#!/usr/bin/env sh
# Detect the Python interpreter that is functional on this machine.
# Source this file to get a PYTHON variable pointing to a working python3.
# Prefers the project virtualenv (.venv) at the repo root when present.
# Falls back to absolute Homebrew paths to bypass broken venv shims on PATH.
#
# Usage: . "$(cd "$(dirname "$0")" && pwd)/python-detect.sh"

_repo_root="$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)"

PYTHON=""

# Prefer project venv if it exists and works
if [ -x "$_repo_root/.venv/bin/python" ] && \
   "$_repo_root/.venv/bin/python" -c "import sys; sys.exit(0)" > /dev/null 2>&1; then
  PYTHON="$_repo_root/.venv/bin/python"
fi

# Reuse the installed Echelon CLI venv when this checkout has no local venv.
if [ -z "$PYTHON" ] && [ -x "$HOME/.echelon/venv/bin/python" ] && \
   "$HOME/.echelon/venv/bin/python" -c "import sys; sys.exit(0)" > /dev/null 2>&1; then
  PYTHON="$HOME/.echelon/venv/bin/python"
fi

# Fall back to system Python
if [ -z "$PYTHON" ]; then
  for _py_candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 python3.12 python3 python; do
    if { [ -x "$_py_candidate" ] || command -v "$_py_candidate" > /dev/null 2>&1; } && \
       "$_py_candidate" -c "import sys; sys.exit(0)" > /dev/null 2>&1; then
      PYTHON="$_py_candidate"
      break
    fi
  done
fi

if [ -z "$PYTHON" ]; then
  echo "ERROR: No working Python interpreter found. Tried: .venv/bin/python, ~/.echelon/venv/bin/python, /opt/homebrew/bin/python3.12, python3.12, python3, python" >&2
  exit 1
fi

unset _py_candidate _repo_root
