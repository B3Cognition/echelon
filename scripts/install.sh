#!/usr/bin/env bash
# install.sh — One-command setup for echelon (includes harness)
# Usage: bash scripts/install.sh [--help]
set -e

_usage() {
  cat <<'EOF'
Usage: bash scripts/install.sh [--help]

Options:
  --help  Show this help without changing the system.
EOF
}

if [ "$#" -gt 1 ]; then
  echo "✗ Expected at most one option." >&2
  _usage >&2
  exit 2
fi
case "$1" in
  "") ;;
  --help)
    _usage
    exit 0
    ;;
  *)
    echo "✗ Unknown option: $1" >&2
    _usage >&2
    exit 2
    ;;
esac

ECHELON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEGRAPH_CLI_VERSION="1.4.1"
PROSAIC_GIT_SPEC="git+ssh://git@github.com/B3Cognition/prosaic.git#b6c9701"
VENV_DIR="$HOME/.echelon/venv"
MEMORY_DIR="$HOME/.echelon/memory"
NODE_RUNTIME_ROOT="${ECHELON_HOME:-$HOME/.echelon}/node"
CODEGRAPH_SOURCE_DIR="$ECHELON_DIR/runtime/scripts/node/codegraph"
PERLGRAPH_SOURCE_DIR="$ECHELON_DIR/runtime/scripts/node/perlgraph"
CTX7_SOURCE_DIR="$ECHELON_DIR/runtime/scripts/node/context7"
CODEGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/codegraph"
PERLGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/perlgraph"
CTX7_NODE_DIR="$NODE_RUNTIME_ROOT/context7"
PROSAIC_NODE_DIR="$NODE_RUNTIME_ROOT/prosaic"
PROSAIC_LAUNCHER="$VENV_DIR/bin/prosaic"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         echelon — installer              ║"
echo "╚══════════════════════════════════════════╝"
echo ""

_refresh_node_runtime() {
  local source_dir="$1"
  local runtime_dir="$2"
  shift 2

  if [ ! -d "$source_dir" ]; then
    echo "  ✗ Node runtime source not found: $source_dir" >&2
    return 1
  fi

  rm -rf "$runtime_dir"
  mkdir -p "$(dirname "$runtime_dir")"
  cp -R "$source_dir" "$runtime_dir"
  rm -rf "$runtime_dir/node_modules"
  while [ "$#" -gt 0 ]; do
    rm -rf "$runtime_dir/$1"
    shift
  done
}

_npm_ci_in_runtime() {
  local runtime_dir="$1"
  shift
  (
    cd "$runtime_dir"
    npm ci "$@"
  )
}

_npm_run_in_runtime() {
  local runtime_dir="$1"
  shift
  (
    cd "$runtime_dir"
    npm run "$@"
  )
}

# ── Shell RC detection ───────────────────────────────────────────────────────
_detect_shell_rc() {
  case "${SHELL##*/}" in
    zsh)  echo "$HOME/.zshrc" ;;
    bash) echo "$HOME/.bashrc" ;;
    *)    echo "$HOME/.profile" ;;
  esac
}
SHELL_RC="$(_detect_shell_rc)"

# ── uv check ─────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo "  ✗ uv not found. Install it first:"
  echo "    macOS : brew install uv"
  echo "    other : curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# ── 1. echelon venv (core tools + shared dependencies) ──────────────────────
echo "▶ Installing echelon into $VENV_DIR..."
uv venv "$VENV_DIR" -q 2>/dev/null || true
# The installed package is editable.  Reinstall it so changing checkout paths
# (for example after merging from a worktree) updates the editable .pth target
# even when the package version itself has not changed.
uv pip install -q --reinstall --python "$VENV_DIR" -e "$ECHELON_DIR"
echo "  ℹ pdftotext (Poppler) is recommended for higher-fidelity PDF extraction; it was not installed."

ECHELON_VER=$("$VENV_DIR/bin/echelon" --version 2>/dev/null || echo "unknown")
echo "  ✓ echelon installed ($ECHELON_VER)"
echo "    echelon       → $VENV_DIR/bin/echelon"
echo "    understanding → $VENV_DIR/bin/understanding"
echo "    harness       → $VENV_DIR/bin/harness"

# Add venv/bin to PATH if needed (idempotent)
if ! grep -qF "$VENV_DIR/bin" "$SHELL_RC"; then
  echo "  Adding $VENV_DIR/bin to PATH in $SHELL_RC"
  printf '\n# echelon CLI tools\nexport PATH="%s/bin:$PATH"\n' "$VENV_DIR" >> "$SHELL_RC"
  export PATH="$VENV_DIR/bin:$PATH"
  echo "  ✓ Added to PATH (restart terminal or: source $SHELL_RC)"
else
  echo "  ✓ echelon tools on PATH"
fi

# ── 2b. Pre-convert journal-entry-types.yaml to JSON ─────────────────────────
echo "▶ Converting journal-entry-types.yaml to JSON..."
JETYPES_YAML="$ECHELON_DIR/runtime/workflow/journal-entry-types.yaml"
JETYPES_JSON="$ECHELON_DIR/runtime/workflow/journal-entry-types.json"
"$VENV_DIR/bin/python" -c "
import yaml, json, sys
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
with open(sys.argv[2], 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
" "$JETYPES_YAML" "$JETYPES_JSON"
echo "  ✓ journal-entry-types.json generated"

# ── 3. RE CodeGraph bridge dependencies ─────────────────────────────────────
echo "▶ Installing RE CodeGraph bridge dependencies..."
if ! command -v node &>/dev/null; then
  echo "  ⚠ Node.js not found; CodeGraph structural analysis will be skipped."
  echo "    Install Node.js, then rerun this installer."
elif ! command -v npm &>/dev/null; then
  echo "  ⚠ npm not found; CodeGraph structural analysis will be skipped."
  echo "    Install npm, then rerun this installer."
elif [ ! -f "$CODEGRAPH_SOURCE_DIR/package-lock.json" ]; then
  echo "  ⚠ package-lock.json not found at $CODEGRAPH_SOURCE_DIR; skipping CodeGraph bridge deps."
else
  _refresh_node_runtime "$CODEGRAPH_SOURCE_DIR" "$CODEGRAPH_NODE_DIR" dist
  _npm_ci_in_runtime "$CODEGRAPH_NODE_DIR" --ignore-scripts --no-audit --no-fund --prefer-offline --silent
  echo "  ✓ CodeGraph bridge dependencies installed → $CODEGRAPH_NODE_DIR/node_modules"
fi

# ── 3b. Optional upstream CodeGraph CLI ─────────────────────────────────────
echo "▶ Checking upstream CodeGraph CLI..."
if command -v codegraph &>/dev/null; then
  CODEGRAPH_CLI_VER="$(codegraph version 2>/dev/null || codegraph --version 2>/dev/null || echo "installed")"
  if [ "$CODEGRAPH_CLI_VER" = "$CODEGRAPH_CLI_VERSION" ]; then
    echo "  ✓ CodeGraph CLI found ($CODEGRAPH_CLI_VER)"
  elif [ "${ECHELON_INSTALL_CODEGRAPH_CLI:-0}" = "1" ]; then
    if command -v npm &>/dev/null; then
      npm install -g "@colbymchenry/codegraph@$CODEGRAPH_CLI_VERSION" --silent
      echo "  ✓ CodeGraph CLI updated to $CODEGRAPH_CLI_VERSION"
    else
      echo "  ⚠ CodeGraph CLI is $CODEGRAPH_CLI_VER; pinned version is $CODEGRAPH_CLI_VERSION."
      echo "    npm not found; cannot update CodeGraph CLI."
    fi
  else
    echo "  ⚠ CodeGraph CLI is $CODEGRAPH_CLI_VER; pinned version is $CODEGRAPH_CLI_VERSION."
    echo "    Update with: ECHELON_INSTALL_CODEGRAPH_CLI=1 bash scripts/install.sh"
  fi
elif [ "${ECHELON_INSTALL_CODEGRAPH_CLI:-0}" = "1" ]; then
  if command -v npm &>/dev/null; then
    npm install -g "@colbymchenry/codegraph@$CODEGRAPH_CLI_VERSION" --silent
    echo "  ✓ CodeGraph CLI installed ($CODEGRAPH_CLI_VERSION)"
  else
    echo "  ⚠ npm not found; cannot install CodeGraph CLI."
  fi
else
  echo "  ℹ CodeGraph CLI not found; optional install:"
  echo "    ECHELON_INSTALL_CODEGRAPH_CLI=1 bash scripts/install.sh"
fi

# ── 3c. RE PerlGraph runtime dependencies ───────────────────────────────────
echo "▶ Installing RE PerlGraph runtime dependencies..."
if ! command -v node &>/dev/null; then
  echo "  ⚠ Node.js not found; PerlGraph structural analysis will be skipped."
  echo "    Install Node.js, then rerun this installer."
elif ! command -v npm &>/dev/null; then
  echo "  ⚠ npm not found; PerlGraph structural analysis will be skipped."
  echo "    Install npm, then rerun this installer."
elif [ ! -f "$PERLGRAPH_SOURCE_DIR/package-lock.json" ]; then
  echo "  ⚠ package-lock.json not found at $PERLGRAPH_SOURCE_DIR; skipping PerlGraph runtime deps."
else
  _refresh_node_runtime "$PERLGRAPH_SOURCE_DIR" "$PERLGRAPH_NODE_DIR" dist
  CXXFLAGS="${CXXFLAGS:--std=c++20}" _npm_ci_in_runtime "$PERLGRAPH_NODE_DIR" --include=dev --no-audit --no-fund --prefer-offline --silent
  _npm_run_in_runtime "$PERLGRAPH_NODE_DIR" build --silent
  echo "  ✓ PerlGraph runtime dependencies installed → $PERLGRAPH_NODE_DIR/node_modules"
  echo "  ✓ PerlGraph CLI built → $PERLGRAPH_NODE_DIR/dist/cli/perlgraph.js"
fi

# ── 3d. Context7 documentation tool dependencies ────────────────────────────
echo "▶ Installing Context7 documentation tool dependencies..."
if ! command -v node &>/dev/null; then
  echo "  ⚠ Node.js not found; Context7 documentation lookups will be unavailable."
  echo "    Install Node.js, then rerun this installer."
elif ! command -v npm &>/dev/null; then
  echo "  ⚠ npm not found; Context7 documentation lookups will be unavailable."
  echo "    Install npm, then rerun this installer."
elif [ ! -f "$CTX7_SOURCE_DIR/package-lock.json" ]; then
  echo "  ⚠ package-lock.json not found at $CTX7_SOURCE_DIR; skipping Context7 deps."
else
  _refresh_node_runtime "$CTX7_SOURCE_DIR" "$CTX7_NODE_DIR" dist
  _npm_ci_in_runtime "$CTX7_NODE_DIR" --silent
  echo "  ✓ Context7 CLI dependencies installed → $CTX7_NODE_DIR/node_modules"
fi

# ── 3e. Prosaic package deployment runtime ───────────────────────────────────
echo "▶ Installing Prosaic package deployment runtime..."
if ! command -v node &>/dev/null; then
  echo "  ⚠ Node.js not found; Prosaic workspace bundle deployment will be unavailable."
  rm -f "$PROSAIC_LAUNCHER"
elif ! command -v npm &>/dev/null; then
  echo "  ⚠ npm not found; Prosaic workspace bundle deployment will be unavailable."
  rm -f "$PROSAIC_LAUNCHER"
else
  mkdir -p "$PROSAIC_NODE_DIR"
  npm install --prefix "$PROSAIC_NODE_DIR" --no-audit --no-fund "$PROSAIC_GIT_SPEC"
  cat > "$PROSAIC_LAUNCHER" <<EOF
#!/usr/bin/env bash
exec node "$PROSAIC_NODE_DIR/node_modules/prosaic/dist/cli/index.js" "\$@"
EOF
  chmod +x "$PROSAIC_LAUNCHER"
  echo "  ✓ Prosaic runtime installed → $PROSAIC_NODE_DIR/node_modules"
  echo "  ✓ Prosaic launcher installed → $PROSAIC_LAUNCHER"
fi

# ── 4. Memory directory ──────────────────────────────────────────────────────
echo "▶ Setting up memory directory..."
mkdir -p "$MEMORY_DIR"
chmod 700 "$MEMORY_DIR"
echo "  ✓ $MEMORY_DIR (permissions 700)"

# ── 5. Warm up embedding model ───────────────────────────────────────────────
echo "▶ Warming up embedding model (downloads ~80MB on first run)..."
"$VENV_DIR/bin/python" -c "
import chromadb, os
palace = os.path.expanduser('~/.mempalace/palace')
os.makedirs(palace, exist_ok=True)
client = chromadb.PersistentClient(path=palace)
try:
    col = client.get_collection('mempalace_drawers')
except Exception:
    col = client.create_collection('mempalace_drawers')
col.add(documents=['warmup'], ids=['warmup-001'], metadatas=[{'wing':'_warmup','room':'_warmup'}])
col.delete(ids=['warmup-001'])
print('  ✓ Embedding model ready')
" 2>/dev/null && echo "  ✓ Model cached" || echo "  ✓ Model will download on first use"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║              Install complete            ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  echelon       → $VENV_DIR/bin/echelon"
echo "  understanding → $VENV_DIR/bin/understanding"
echo "  harness       → $VENV_DIR/bin/harness"
if [ -d "$CODEGRAPH_NODE_DIR/node_modules" ]; then
  echo "  CodeGraph bridge → $CODEGRAPH_NODE_DIR/node_modules"
else
  echo "  CodeGraph bridge → not ready (rerun this installer after installing Node.js/npm)"
fi
if command -v codegraph &>/dev/null; then
  echo "  CodeGraph CLI    → $(command -v codegraph)"
else
  echo "  CodeGraph CLI    → optional (ECHELON_INSTALL_CODEGRAPH_CLI=1 bash scripts/install.sh)"
fi
if [ -x "$PERLGRAPH_NODE_DIR/dist/cli/perlgraph.js" ]; then
  echo "  PerlGraph CLI  → $PERLGRAPH_NODE_DIR/dist/cli/perlgraph.js"
else
  echo "  PerlGraph CLI  → not ready (rerun this installer after installing Node.js/npm)"
fi
if [ -x "$CTX7_NODE_DIR/node_modules/.bin/ctx7" ]; then
  echo "  Context7 CLI  → $CTX7_NODE_DIR/node_modules/.bin/ctx7"
else
  echo "  Context7 CLI  → not ready (rerun this installer after installing Node.js/npm)"
fi
if [ -x "$PROSAIC_LAUNCHER" ]; then
  echo "  Prosaic       → $PROSAIC_LAUNCHER"
else
  echo "  Prosaic       → not ready (rerun this installer after installing Node.js/npm)"
fi
echo "  Memory        → $MEMORY_DIR"
echo ""
echo "  Per-project setup (deploys Prosaic and runtime bundles):"
echo "    echelon workspace init    # workspace config, local approvals, git hook"
echo "    echelon delivery init     # delivery config, mirror clone, image fingerprint"
echo ""
echo "  Run a feature:"
echo "    echelon spec run \"add user notifications\""
echo "    echelon delivery run 001"
echo ""
