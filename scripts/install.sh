#!/usr/bin/env bash
# install.sh — One-command setup for echelon + harness
# Usage: bash scripts/install.sh
set -e

ECHELON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS_DIR="$(cd "$ECHELON_DIR/../echelon-harness" 2>/dev/null && pwd || true)"
SOAR_VERSION="9.6.4"
SOAR_DIR="$HOME/.echelon/soar"
VENV_DIR="$HOME/.echelon/venv"
MEMORY_DIR="$HOME/.echelon/memory"
CONFIG_FILE="$HOME/.echelon/memory-config.yml"

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
echo "  ✓ echelon installed"
echo "    echelon       → $VENV_DIR/bin/echelon"
echo "    codegen       → $VENV_DIR/bin/codegen"
echo "    understanding → $VENV_DIR/bin/understanding"

# ── 2b. harness (optional — skipped if echelon-harness not found) ─────────────
echo "▶ Installing harness..."
if [ -n "$HARNESS_DIR" ] && [ -f "$HARNESS_DIR/pyproject.toml" ]; then
  uv pip install -q --python "$VENV_DIR" -e "$HARNESS_DIR"
  echo "  ✓ harness installed"
  echo "    harness → $VENV_DIR/bin/harness"
else
  echo "  ℹ  echelon-harness not found at $ECHELON_DIR/../echelon-harness — skipping"
  echo "     To install later: uv pip install -e /path/to/echelon-harness --python $VENV_DIR"
fi

# Add venv/bin to PATH if needed (idempotent)
if ! grep -qF "$VENV_DIR/bin" "$SHELL_RC"; then
  echo "  Adding $VENV_DIR/bin to PATH in $SHELL_RC"
  printf '\n# echelon CLI tools\nexport PATH="%s/bin:$PATH"\n' "$VENV_DIR" >> "$SHELL_RC"
  export PATH="$VENV_DIR/bin:$PATH"
  echo "  ✓ Added to PATH (restart terminal or: source $SHELL_RC)"
else
  echo "  ✓ echelon tools on PATH"
fi

# ── 3. Memory directory ──────────────────────────────────────────────────────
echo "▶ Setting up memory directory..."
mkdir -p "$MEMORY_DIR"
chmod 700 "$MEMORY_DIR"
echo "  ✓ $MEMORY_DIR (permissions 700)"

# ── 4. memory-config.yml ─────────────────────────────────────────────────────
echo "▶ Writing memory-config.yml..."
if [ -f "$CONFIG_FILE" ]; then
  echo "  ℹ  $CONFIG_FILE already exists — skipping (delete to regenerate)"
else
  cat > "$CONFIG_FILE" <<EOF
# echelon persistent memory configuration (codegen pipeline)

epmem_db_path: ~/.echelon/memory/epmem.db
smem_db_path: ~/.echelon/memory/smem.db
mempalace_palace_path: ~/.mempalace/palace
embedding_model_name: all-MiniLM-L6-v2
embedding_model_version: "1.0"
max_epmem_episodes: 10000
smem_accumulation_min_psi: 0.70
epmem_impasse_min_match_score: 0.80
EOF
  echo "  ✓ $CONFIG_FILE written"
fi

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
echo "  SOAR          → $SOAR_DIR/bin/soar"
echo "  echelon       → $VENV_DIR/bin/echelon"
echo "  codegen       → $VENV_DIR/bin/codegen"
echo "  understanding → $VENV_DIR/bin/understanding"
if [ -n "$HARNESS_DIR" ] && [ -f "$HARNESS_DIR/pyproject.toml" ]; then
echo "  harness       → $VENV_DIR/bin/harness"
fi
echo "  Memory        → $MEMORY_DIR"
echo "  Config        → $CONFIG_FILE"
echo ""
echo "  Register the spec-kit extension (covers echelon + harness skills):"
echo "    specify extension add --dev $ECHELON_DIR/extension"
echo ""
echo "  Per-project setup:"
echo "    echelon init    # deploy infra (echelon.yml, Docker/Traefik, git hook)"
echo "    harness init    # harness config, mirror clone, image fingerprint"
echo ""
echo "  Run a feature:"
echo "    echelon run \"add user notifications\""
echo "    harness run 001"
echo ""
