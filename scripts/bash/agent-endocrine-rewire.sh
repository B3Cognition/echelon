#!/usr/bin/env bash
# agent-endocrine-rewire.sh — Idempotent inserter for the endocrine-awareness
# marker line in every agent .md file under extension/agents/<layer>/ and the
# deployed copies under .specify/extensions/echelon/agents/<layer>/.
#
# Usage:
#   bash agent-endocrine-rewire.sh [--dry-run] [--remove]
#
# Inserts (after each agent's "## Role" body, before the next "##" heading):
#
#   > **Endocrine awareness.** Your dispatched context pack includes an
#   > `[ENDOCRINE]` block from `endocrine.sh get_full_prompt_modifier`:
#   > your current hormone levels … plus role-appropriate interpretation
#   > from your archetype. It's not narration — it's behavior modulation.
#   > Read and act on it before producing output.
#
# Idempotent: re-running on a file that already contains the marker is a no-op.
# --dry-run: prints planned changes, writes nothing.
# --remove: strips the marker block (clean rollback). Idempotent.
#
# Exit codes:
#   0 = success (or dry-run completed)
#   1 = called outside a project root, OR a file lacks "## Role" heading

set -euo pipefail

DRY_RUN=false
REMOVE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --remove)  REMOVE=true; shift ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "agent-endocrine-rewire: unknown arg: $1" >&2; exit 1 ;;
  esac
done

ROOT="$(pwd)"
while [ "$ROOT" != "/" ] && [ ! -d "$ROOT/.specify" ]; do
  ROOT=$(dirname "$ROOT")
done
if [ "$ROOT" = "/" ]; then
  echo "agent-endocrine-rewire: no .specify/ in CWD or parents" >&2
  exit 1
fi
cd "$ROOT"

MARKER="**Endocrine awareness.**"

# Two agent-file directories to process (source + deployed copies).
DIRS=(
  "extension/agents"
  ".specify/extensions/echelon/agents"
)

processed=0
inserted=0
skipped=0
removed=0
errors=0

for base in "${DIRS[@]}"; do
  if [ ! -d "$base" ]; then
    echo "  (skip — $base not present)"
    continue
  fi
  while IFS= read -r -d '' f; do
    processed=$((processed + 1))

    if $REMOVE; then
      if grep -qF "$MARKER" "$f"; then
        if $DRY_RUN; then
          echo "  WOULD REMOVE marker in $f"
        else
          python3 - "$f" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path).read()
# Remove the blockquote line(s) containing the marker plus its surrounding
# blank lines, idempotently. The marker is a single blockquote line we insert.
new = re.sub(r'\n\n> \*\*Endocrine awareness\.\*\*[^\n]*\n', '\n', text, count=1)
open(path, 'w').write(new)
PY
        fi
        removed=$((removed + 1))
      else
        skipped=$((skipped + 1))
      fi
      continue
    fi

    if grep -qF "$MARKER" "$f"; then
      skipped=$((skipped + 1))
      continue
    fi

    if ! grep -qE '^## [Rr]ole' "$f"; then
      echo "  ERROR — $f has no '## Role' heading" >&2
      errors=$((errors + 1))
      continue
    fi

    if $DRY_RUN; then
      echo "  WOULD INSERT marker in $f"
      inserted=$((inserted + 1))
      continue
    fi

    python3 - "$f" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path).read()
# Find "## Role" heading line; insert marker block before the next H2.
m = re.search(r'^## [Rr]ole.*?$', text, flags=re.M)
if not m:
    raise SystemExit(f"no role heading after grep matched — internal error: {path}")
start = m.end()
# Find next "## " H2 after the Role body (or EOF)
next_h2 = re.search(r'^## ', text[start:], flags=re.M)
insertion_pos = start + (next_h2.start() if next_h2 else len(text) - start)

block = "> **Endocrine awareness.** Your dispatched context pack includes an `[ENDOCRINE]` block from `endocrine.sh get_full_prompt_modifier`: your current hormone levels (adrenaline, dopamine, cortisol, serotonin, oxytocin, norepinephrine) plus role-appropriate interpretation from your archetype. It's not narration — it's behavior modulation. Read and act on it before producing output."

new_text = text[:insertion_pos].rstrip() + "\n\n" + block + "\n\n" + text[insertion_pos:].lstrip()
open(path, 'w').write(new_text)
PY
    inserted=$((inserted + 1))
  done < <(find "$base" -type f -name "*.md" -print0)
done

echo
echo "agent-endocrine-rewire summary:"
echo "  processed: $processed"
echo "  inserted:  $inserted"
echo "  removed:   $removed"
echo "  skipped:   $skipped  (already had marker, or didn't have one to remove)"
echo "  errors:    $errors"
exit $((errors == 0 ? 0 : 1))
