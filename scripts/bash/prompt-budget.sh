#!/usr/bin/env bash
# prompt-budget.sh — Monitor agent prompt sizes against budget
#
# Usage:
#   prompt-budget.sh check [--max N]     — check all agents, exit 1 if any exceed max (default 500)
#   prompt-budget.sh report              — print full size report
#   prompt-budget.sh top [N]             — show top N largest agents (default 10)
#
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${PROMPT_BUDGET_REPO_ROOT:-$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)}"
AGENTS_DIR="$REPO_ROOT/agents"
DEFAULT_MAX=500

cmd="${1:-report}"
shift || true

case "$cmd" in
  check)
    max="$DEFAULT_MAX"
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --max) shift; max="$1" ;;
      esac
      shift
    done

    violations=0
    total=0
    while IFS= read -r f; do
      lines=$(wc -l < "$f")
      total=$((total + 1))
      if [[ "$lines" -gt "$max" ]]; then
        name=$(basename "$f" .md)
        layer=$(basename "$(dirname "$f")")
        printf 'VIOLATION: %s/%s = %d lines (max: %d)\n' "$layer" "$name" "$lines" "$max"
        violations=$((violations + 1))
      fi
    done < <(find "$AGENTS_DIR" -name "*.md" -type f | sort)

    if [[ "$violations" -gt 0 ]]; then
      printf '\n%d/%d agents exceed %d-line budget\n' "$violations" "$total" "$max"
      exit 1
    else
      printf 'All %d agents within %d-line budget\n' "$total" "$max"
      exit 0
    fi
    ;;

  report)
    printf '%-30s %-15s %6s  %s\n' "AGENT" "LAYER" "LINES" "STATUS"
    printf '%.0s─' {1..65}; echo
    total_lines=0
    total_agents=0
    while IFS= read -r f; do
      lines=$(wc -l < "$f")
      name=$(basename "$f" .md)
      layer=$(basename "$(dirname "$f")")
      status=""
      [[ "$lines" -gt "$DEFAULT_MAX" ]] && status="⚠ OVER"
      printf '%-30s %-15s %6d  %s\n' "$name" "$layer" "$lines" "$status"
      total_lines=$((total_lines + lines))
      total_agents=$((total_agents + 1))
    done < <(find "$AGENTS_DIR" -name "*.md" -type f -exec sh -c 'echo "$(wc -l < "$1") $1"' _ {} \; | sort -rn | awk '{print $2}')
    printf '%.0s─' {1..65}; echo
    printf '%-30s %-15s %6d\n' "TOTAL ($total_agents agents)" "" "$total_lines"
    printf '%-30s %-15s %6d\n' "AVERAGE" "" "$((total_lines / total_agents))"
    ;;

  top)
    n="${1:-10}"
    printf '%-4s %-30s %-15s %6s\n' "RANK" "AGENT" "LAYER" "LINES"
    printf '%.0s─' {1..60}; echo
    rank=0
    while IFS= read -r f; do
      lines=$(wc -l < "$f")
      name=$(basename "$f" .md)
      layer=$(basename "$(dirname "$f")")
      rank=$((rank + 1))
      printf '%-4d %-30s %-15s %6d\n' "$rank" "$name" "$layer" "$lines"
    done < <(find "$AGENTS_DIR" -name "*.md" -type f -exec sh -c 'echo "$(wc -l < "$1") $1"' _ {} \; | sort -rn | head -"$n" | awk '{print $2}')
    ;;

  *)
    echo "Usage: prompt-budget.sh {check [--max N]|report|top [N]}" >&2
    exit 1
    ;;
esac
