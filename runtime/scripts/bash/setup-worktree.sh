#!/usr/bin/env bash
# setup-worktree.sh — Create a throwaway git worktree for SCIENTIST experiments
# Usage: setup-worktree.sh [experiment-name]

set -euo pipefail

EXPERIMENT="${1:-experiment}"
TIMESTAMP=$(date +%s)
WORKTREE_DIR="/tmp/squad-experiment-${EXPERIMENT}-${TIMESTAMP}"

git worktree add "$WORKTREE_DIR" HEAD --detach 2>/dev/null

echo "$WORKTREE_DIR"
