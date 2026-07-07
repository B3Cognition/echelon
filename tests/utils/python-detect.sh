#!/usr/bin/env sh
# Detect the Python interpreter that is functional on this machine.
# Source this file to get a PYTHON variable pointing to a working python3.
# Prefers the project virtualenv (.venv) at the repo root when present.
# Falls back to absolute Homebrew paths to bypass broken venv shims on PATH.
#
# Usage: . "$(cd "$(dirname "$0")/.." && pwd)/utils/python-detect.sh"

_repo_root="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"

_python_works() {
  "$1" -c "import sys; import typer; sys.exit(0)" > /dev/null 2>&1
}

if [ -n "${PYTHON:-}" ] && _python_works "$PYTHON"; then
  PYTHON="$PYTHON"
else
  PYTHON=""
fi

# Prefer project venv if it exists and works
if [ -z "$PYTHON" ] && [ -x "$_repo_root/.venv/bin/python" ] && \
   _python_works "$_repo_root/.venv/bin/python"; then
  PYTHON="$_repo_root/.venv/bin/python"
fi

# Reuse the installed Echelon CLI venv when this checkout has no local venv.
if [ -z "$PYTHON" ] && [ -x "$HOME/.echelon/venv/bin/python" ] && \
   _python_works "$HOME/.echelon/venv/bin/python"; then
  PYTHON="$HOME/.echelon/venv/bin/python"
fi

# Fall back to system Python
if [ -z "$PYTHON" ]; then
  for _py_candidate in /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 python3.12 python3 python; do
    if { [ -x "$_py_candidate" ] || command -v "$_py_candidate" > /dev/null 2>&1; } && \
       _python_works "$_py_candidate"; then
      PYTHON="$_py_candidate"
      break
    fi
  done
fi

if [ -z "$PYTHON" ]; then
  echo "ERROR: No working Python interpreter with Echelon dependencies found. Tried: inherited \$PYTHON, .venv/bin/python, ~/.echelon/venv/bin/python, /opt/homebrew/bin/python3.12, python3.12, python3, python" >&2
  exit 1
fi

unset _py_candidate _python_works _repo_root
