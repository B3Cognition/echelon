#!/usr/bin/env bash
# install.sh — One-command setup for echelon (includes harness)
# Usage: bash scripts/install.sh
set -e

ECHELON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOAR_VERSION="9.6.4"
SOAR_DIR="$HOME/.echelon/soar"
VENV_DIR="$HOME/.echelon/venv"
MEMORY_DIR="$HOME/.echelon/memory"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         echelon — installer              ║"
echo "╚══════════════════════════════════════════╝"
echo ""

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

# ── Detect platform ──────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS/$ARCH" in
  Darwin/arm64)   PLATFORM="mac_ARM64" ;;
  Darwin/x86_64)  PLATFORM="mac_x86-64" ;;
  Linux/x86_64)   PLATFORM="linux_x86-64" ;;
  *)
    echo "  ✗ Unsupported platform: $OS/$ARCH"
    exit 1
    ;;
esac

# ── 1. Download SoarSuite from GitHub releases ────────────────────────────────
_download_soar() {
  local zip_url="https://github.com/SoarGroup/Soar/releases/download/releases%2F${SOAR_VERSION}/SoarSuite_${SOAR_VERSION}-Multiplatform.zip"
  local zip_tmp extract_tmp

  zip_tmp="$(mktemp -t soarsuite.XXXXXX).zip"
  extract_tmp="$(mktemp -d)"

  echo "  Downloading SoarSuite_${SOAR_VERSION}-Multiplatform.zip..."
  curl -fL --progress-bar "$zip_url" -o "$zip_tmp"

  echo "  Extracting $PLATFORM binaries..."
  unzip -q "$zip_tmp" -d "$extract_tmp"
  rm -f "$zip_tmp"

  local soar_bin_src
  soar_bin_src="$(find "$extract_tmp" -type f -name "soar" -path "*/$PLATFORM/*" | head -1)"
  if [ -z "$soar_bin_src" ]; then
    echo "  ✗ Could not find $PLATFORM/soar inside the zip"
    rm -rf "$extract_tmp"
    exit 1
  fi
  mkdir -p "$SOAR_DIR/bin"
  cp "$(dirname "$soar_bin_src")"/* "$SOAR_DIR/bin/"
  chmod +x "$SOAR_DIR/bin/soar"
  echo "  ✓ SOAR ${SOAR_VERSION} → $SOAR_DIR/bin/"

  rm -rf "$extract_tmp"
}

echo "▶ Installing SOAR ${SOAR_VERSION}..."
if [ -f "$SOAR_DIR/bin/soar" ]; then
  echo "  ✓ SOAR already at $SOAR_DIR/bin/ (delete $SOAR_DIR to re-download)"
else
  _download_soar
fi

# Add SOAR to PATH if needed (idempotent — checks file, not current session)
if ! grep -qF "$SOAR_DIR/bin" "$SHELL_RC"; then
  echo "  Adding $SOAR_DIR/bin to PATH in $SHELL_RC"
  printf '\n# SOAR binary (echelon dependency)\nexport PATH="%s/bin:$PATH"\n' "$SOAR_DIR" >> "$SHELL_RC"
  export PATH="$SOAR_DIR/bin:$PATH"
  echo "  ✓ Added to PATH (restart terminal or: source $SHELL_RC)"
else
  echo "  ✓ SOAR on PATH"
fi

# ── 2. echelon venv (echelon + codegen + understanding + all deps) ───────────
echo "▶ Installing echelon into $VENV_DIR..."
uv venv "$VENV_DIR" -q 2>/dev/null || true
uv pip install -q --python "$VENV_DIR" -e "$ECHELON_DIR"
ECHELON_VER=$("$VENV_DIR/bin/echelon" --version 2>/dev/null || echo "unknown")
echo "  ✓ echelon installed ($ECHELON_VER)"
echo "    echelon       → $VENV_DIR/bin/echelon"
echo "    codegen       → $VENV_DIR/bin/codegen"
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
JETYPES_YAML="$ECHELON_DIR/extension/workflow/journal-entry-types.yaml"
JETYPES_JSON="$ECHELON_DIR/extension/workflow/journal-entry-types.json"
"$VENV_DIR/bin/python" -c "
import yaml, json, sys
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
with open(sys.argv[2], 'w') as f:
    json.dump(data, f, indent=2)
" "$JETYPES_YAML" "$JETYPES_JSON"
echo "  ✓ journal-entry-types.json generated"

# ── 3. Memory directory ──────────────────────────────────────────────────────
echo "▶ Setting up memory directory..."
mkdir -p "$MEMORY_DIR"
chmod 700 "$MEMORY_DIR"
echo "  ✓ $MEMORY_DIR (permissions 700)"

# ── 4. Warm up embedding model ───────────────────────────────────────────────
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
echo "  SOAR          → $SOAR_DIR/bin/soar"
echo "  echelon       → $VENV_DIR/bin/echelon"
echo "  codegen       → $VENV_DIR/bin/codegen"
echo "  understanding → $VENV_DIR/bin/understanding"
echo "  harness       → $VENV_DIR/bin/harness"
echo "  Memory        → $MEMORY_DIR"
echo ""
echo "  Register the spec-kit extension:"
echo "    specify extension add --dev $ECHELON_DIR/extension"
echo ""
echo "  Per-project setup:"
echo "    echelon init    # deploy infra (echelon-config.yml, Docker/Traefik, git hook)"
echo "    echelon harness init    # harness config, mirror clone, image fingerprint"
echo ""
echo "  Run a feature:"
echo "    echelon run \"add user notifications\""
echo "    echelon harness run 001"
echo ""
