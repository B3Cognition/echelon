#!/usr/bin/env bash
# uninstall.sh — Remove echelon + harness runtime: SOAR, venv, memory, config, PATH entries
# Usage: bash scripts/uninstall.sh [--purge-memory]
#   --purge-memory  also deletes ~/.echelon/memory/ and ~/.mempalace/
# Note: harness is installed into the same venv — removing the venv removes both.
set -e

SOAR_DIR="$HOME/.echelon/soar"
VENV_DIR="$HOME/.echelon/venv"
MEMORY_DIR="$HOME/.echelon/memory"
CONFIG_FILE="$HOME/.echelon/memory-config.yml"
ECHELON_HOME="${ECHELON_HOME:-$HOME/.echelon}"
NODE_RUNTIME_DIR="$ECHELON_HOME/node"
MEMPALACE_DIR="$HOME/.mempalace"

PURGE_MEMORY=false
for arg in "$@"; do
  [[ "$arg" == "--purge-memory" ]] && PURGE_MEMORY=true
done

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         echelon — uninstaller            ║"
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

# ── 1. SOAR ──────────────────────────────────────────────────────────────────
echo "▶ Removing SOAR..."
if [ -d "$SOAR_DIR" ]; then
  rm -rf "$SOAR_DIR"
  echo "  ✓ Removed $SOAR_DIR"
else
  echo "  ✓ $SOAR_DIR not found — skipping"
fi

# ── 2. echelon + harness venv ────────────────────────────────────────────────
echo "▶ Removing echelon + harness venv..."
if [ -d "$VENV_DIR" ]; then
  rm -rf "$VENV_DIR"
  echo "  ✓ Removed $VENV_DIR"
else
  echo "  ✓ $VENV_DIR not found — skipping"
fi

# ── 3. Shared Node runtimes ──────────────────────────────────────────────────
echo "▶ Removing shared Node runtimes..."
if [ -d "$NODE_RUNTIME_DIR" ]; then
  rm -rf "$NODE_RUNTIME_DIR"
  echo "  ✓ Removed $NODE_RUNTIME_DIR"
else
  echo "  ✓ $NODE_RUNTIME_DIR not found — skipping"
fi

# ── 4. memory-config.yml ─────────────────────────────────────────────────────
echo "▶ Removing memory-config.yml..."
if [ -f "$CONFIG_FILE" ]; then
  rm -f "$CONFIG_FILE"
  echo "  ✓ Removed $CONFIG_FILE"
else
  echo "  ✓ $CONFIG_FILE not found — skipping"
fi

# ── 5. Memory (opt-in) ───────────────────────────────────────────────────────
if [ "$PURGE_MEMORY" = true ]; then
  echo "▶ Purging memory (--purge-memory)..."
  if [ -d "$MEMORY_DIR" ]; then
    rm -rf "$MEMORY_DIR"
    echo "  ✓ Removed $MEMORY_DIR"
  else
    echo "  ✓ $MEMORY_DIR not found — skipping"
  fi
  if [ -d "$MEMPALACE_DIR" ]; then
    rm -rf "$MEMPALACE_DIR"
    echo "  ✓ Removed $MEMPALACE_DIR"
  else
    echo "  ✓ $MEMPALACE_DIR not found — skipping"
  fi
else
  echo "  ℹ  Memory kept at $MEMORY_DIR (pass --purge-memory to delete)"
fi

# ── 6. Remove ~/.echelon if now empty ────────────────────────────────────────
if [ -d "$ECHELON_HOME" ] && [ -z "$(ls -A "$ECHELON_HOME")" ]; then
  rmdir "$ECHELON_HOME"
  echo "  ✓ Removed $ECHELON_HOME (was empty)"
fi

# ── 7. Remove PATH entries from shell RC ─────────────────────────────────────
echo "▶ Cleaning PATH entries from $SHELL_RC..."
CHANGED=false

# Remove the SOAR PATH block (comment + export line)
if grep -qF "$SOAR_DIR/bin" "$SHELL_RC"; then
  # Use a temp file to strip the block: blank line + comment + export
  tmp="$(mktemp)"
  awk -v dir="$SOAR_DIR/bin" '
    /^# SOAR binary \(echelon dependency\)$/ { skip=1; next }
    skip && /export PATH=.*\/\.echelon\/soar\/bin/ { skip=0; next }
    { print }
  ' "$SHELL_RC" > "$tmp"
  mv "$tmp" "$SHELL_RC"
  CHANGED=true
  echo "  ✓ Removed SOAR PATH entry"
fi

# Remove the venv PATH block (comment + export line)
if grep -qF "$VENV_DIR/bin" "$SHELL_RC"; then
  tmp="$(mktemp)"
  awk -v dir="$VENV_DIR/bin" '
    /^# echelon CLI tools$/ { skip=1; next }
    skip && /export PATH=.*\/\.echelon\/venv\/bin/ { skip=0; next }
    { print }
  ' "$SHELL_RC" > "$tmp"
  mv "$tmp" "$SHELL_RC"
  CHANGED=true
  echo "  ✓ Removed echelon CLI tools PATH entry"
fi

if [ "$CHANGED" = false ]; then
  echo "  ✓ No PATH entries found in $SHELL_RC — skipping"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║             Uninstall complete           ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  Restart your terminal or run: source $SHELL_RC"
if [ "$PURGE_MEMORY" = false ] && [ -d "$MEMORY_DIR" ]; then
  echo ""
  echo "  Memory retained at: $MEMORY_DIR"
  echo "  To delete: bash scripts/uninstall.sh --purge-memory"
fi
echo ""
