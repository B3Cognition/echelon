#!/usr/bin/env bash
# Unit test — Section-5 consistency validator (spec
# docs/superpowers/specs/2026-05-16-endocrine-archetype-coherence-design.md).
# Six independent assertions of the four-way coherence:
#   1. ALL_AGENTS → agent_to_archetype (no silent default-control fall-through)
#   2. agent_to_archetype outputs → baselines (every archetype has a baseline)
#   3. baselines → interpretations (every baseline has an interpretation)
#   4. ALL_AGENTS → disk (every roster entry has a .md file)
#   5. disk → ALL_AGENTS (every .md file is in the roster)
#   6. disk → marker (every .md file has the endocrine-awareness blockquote)
#
# Designed to catch BUG-3-shape drift and Section-4 marker drift in CI.

set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
ENDOCRINE="$REPO_ROOT/extension/scripts/bash/endocrine.sh"
CONFIG="$REPO_ROOT/extension/echelon-config.yml"
AGENTS_DIR="$REPO_ROOT/extension/agents"
MARKER='**Endocrine awareness.**'

# Extract ALL_AGENTS from endocrine.sh source (parse the ALL_AGENTS=(…) block).
ALL_AGENTS=()
mapfile -t ALL_AGENTS < <(
  python3 - "$ENDOCRINE" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
m = re.search(r'^ALL_AGENTS=\(([^)]*)\)', text, flags=re.M)
if not m:
    sys.exit(0)
for token in m.group(1).split():
    token = token.strip()
    if token:
        print(token)
PY
)

if [[ ${#ALL_AGENTS[@]} -eq 0 ]]; then
  echo "FAIL: could not parse ALL_AGENTS from $ENDOCRINE"
  exit 1
fi

pass=0
fail=0
section() { printf "\n[%d] %s\n" "$1" "$2"; }
check() {
  local desc="$1" cond="$2"
  if eval "$cond"; then pass=$((pass+1)); printf "  PASS  %s\n" "$desc"
  else fail=$((fail+1)); printf "  FAIL  %s\n" "$desc"; fi
}

# ---------------- Assertion 1 -------------------------------------------------
section 1 "ALL_AGENTS → archetype (no silent default-control fall-through)"

# An agent that hits the *) default branch will return "control", but so do
# agents legitimately in the control archetype. To distinguish, parse the case
# statement directly: every ALL_AGENTS entry must appear as a literal token in
# at least one case branch (other than the *) default).
default_hits=0
default_agents=""
case_agents_in_branches=$(
  python3 - "$ENDOCRINE" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
# Extract the agent_to_archetype function body
m = re.search(r'^agent_to_archetype\(\)\s*\{(.*?)^\}', text, flags=re.M | re.S)
body = m.group(1) if m else ""
# Strip the *) default branch
body = re.sub(r'\*\).*$', '', body, flags=re.S)
# Pull out names inside each case branch, e.g. "    SCOUT|SYNTHESIZER|MODELER)"
names = set()
for line in body.splitlines():
    if ')' not in line or '*' in line or '|' not in line and not re.match(r'\s+[A-Z_]+\)$', line):
        continue
    head = line.split(')', 1)[0]
    for tok in head.split('|'):
        tok = tok.strip()
        if re.fullmatch(r'[A-Z][A-Z0-9_]+', tok):
            names.add(tok)
print(' '.join(sorted(names)))
PY
)

for a in "${ALL_AGENTS[@]}"; do
  if ! grep -qE "(^| )$a( |$)" <<<"$case_agents_in_branches"; then
    default_hits=$((default_hits + 1))
    default_agents="$default_agents $a"
  fi
done
if [[ $default_hits -ne 0 ]]; then
  echo "    silent-default agents:$default_agents"
fi
check "every ALL_AGENTS entry has an explicit archetype case" "[ $default_hits -eq 0 ]"

# ---------------- Assertion 2 -------------------------------------------------
section 2 "archetype outputs → baselines"

# Collect every archetype that agent_to_archetype actually returns (via subcommand).
ARCH_SET=$(for a in "${ALL_AGENTS[@]}"; do bash "$ENDOCRINE" get_archetype "$a" 2>/dev/null; done | sort -u)
BASELINE_ARCHS=$(python3 - "$CONFIG" <<'PY'
import yaml, sys
d = yaml.safe_load(open(sys.argv[1])) or {}
for k in sorted((d.get('endocrine', {}).get('baselines', {}) or {}).keys()):
    print(k)
PY
)

missing_baseline=0
for arch in $ARCH_SET; do
  if ! grep -qx "$arch" <<<"$BASELINE_ARCHS"; then
    missing_baseline=$((missing_baseline + 1))
    echo "    no baseline for archetype: $arch"
  fi
done
check "every archetype has a baseline" "[ $missing_baseline -eq 0 ]"

# ---------------- Assertion 3 -------------------------------------------------
section 3 "baselines → interpretations"

INTERP_ARCHS=$(python3 - "$CONFIG" <<'PY'
import yaml, sys
d = yaml.safe_load(open(sys.argv[1])) or {}
for k in sorted((d.get('endocrine', {}).get('interpretations', {}) or {}).keys()):
    print(k)
PY
)

missing_interp=0
for arch in $BASELINE_ARCHS; do
  if ! grep -qx "$arch" <<<"$INTERP_ARCHS"; then
    missing_interp=$((missing_interp + 1))
    echo "    no interpretation for baseline: $arch"
  fi
done
check "every baseline has an interpretation" "[ $missing_interp -eq 0 ]"

# ---------------- Assertion 4 -------------------------------------------------
section 4 "ALL_AGENTS → disk"

# Map disk filenames to ALL_AGENTS codename form: foo-bar.md → FOO_BAR.
DISK_AGENTS=$(
  find "$AGENTS_DIR" -type f -name '*.md' \
    -exec basename {} .md \; \
  | tr '[:lower:]-' '[:upper:]_' \
  | sort -u
)

missing_disk=0
for a in "${ALL_AGENTS[@]}"; do
  if ! grep -qx "$a" <<<"$DISK_AGENTS"; then
    missing_disk=$((missing_disk + 1))
    echo "    ALL_AGENTS entry has no .md file: $a"
  fi
done
check "every ALL_AGENTS entry has an agent file" "[ $missing_disk -eq 0 ]"

# ---------------- Assertion 5 -------------------------------------------------
section 5 "disk → ALL_AGENTS"

ALL_AGENTS_SORTED=$(printf '%s\n' "${ALL_AGENTS[@]}" | sort -u)

missing_in_list=0
for a in $DISK_AGENTS; do
  if ! grep -qx "$a" <<<"$ALL_AGENTS_SORTED"; then
    missing_in_list=$((missing_in_list + 1))
    echo "    disk file not in ALL_AGENTS: $a"
  fi
done
check "every agent file is in ALL_AGENTS" "[ $missing_in_list -eq 0 ]"

# ---------------- Assertion 6 -------------------------------------------------
section 6 "disk → endocrine-awareness marker"

missing_marker=0
while IFS= read -r -d '' f; do
  if ! grep -qF "$MARKER" "$f"; then
    missing_marker=$((missing_marker + 1))
    echo "    no marker: $f"
  fi
done < <(find "$AGENTS_DIR" -type f -name '*.md' -print0)
check "every agent file contains the marker" "[ $missing_marker -eq 0 ]"

# ---------------- Summary -----------------------------------------------------
echo
echo "Pass: $pass / 6  Fail: $fail"
exit $((fail == 0 ? 0 : 1))
