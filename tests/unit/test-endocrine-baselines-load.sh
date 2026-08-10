#!/usr/bin/env bash
# Unit test — verify endocrine.sh init seeds agents' hormones from their
# archetype baselines in echelon-config.yml (not from a neutral default).
#
# Currently RED until DEP-FIX T2 lands.

set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
ENDOCRINE="$REPO_ROOT/runtime/scripts/bash/endocrine.sh"
CONFIG="$REPO_ROOT/runtime/config-template.yml"

# Isolate state in a temp file so we don't clobber any live state.
TMP_STATE=$(mktemp -t endocrine-baselines-state.XXXXXX.json)
trap 'rm -f "$TMP_STATE"' EXIT
echo "{}" > "$TMP_STATE"
export ENDOCRINE_STATE_FILE="$TMP_STATE"
export ENDOCRINE_CONFIG_FILE="$CONFIG"

bash "$ENDOCRINE" init >/dev/null 2>&1 || { echo "FAIL: endocrine.sh init failed"; exit 1; }

# Load expected baselines from config.
EXPECTED=$(python3 -c "
import yaml
d = yaml.safe_load(open('$CONFIG'))
b = d['endocrine']['baselines']
for arch, vals in b.items():
    print(f'{arch}:' + ','.join(str(v) for v in vals))
")

# Read actual hormone values for each agent from the state file.
ACTUAL=$(python3 -c "
import json
s = json.load(open('$TMP_STATE'))
agents = s['endocrine_state']['agents']
order = ['adrenaline','dopamine','cortisol','serotonin','oxytocin','norepinephrine']
for a, info in agents.items():
    h = info.get('hormones', {})
    vals = ','.join(str(h.get(k, '?')) for k in order)
    arch = info.get('archetype', '?')
    print(f'{a}|{arch}|{vals}')
")

pass=0
fail=0
report() {
  local name="$1" want="$2" got="$3"
  if [[ "$want" == "$got" ]]; then
    pass=$((pass+1)); printf "  PASS  %-15s baseline matches: %s\n" "$name" "$got"
  else
    fail=$((fail+1)); printf "  FAIL  %-15s want=%s got=%s\n" "$name" "$want" "$got"
  fi
}

# Check 7 representative agents from different archetypes. Keep the fixture
# compatible with macOS's system Bash 3.2, which has no associative arrays.
echo "Hormone baselines per archetype (post-init):"
while IFS='|' read -r agent arch; do
  expected=$(echo "$EXPECTED" | grep "^${arch}:" | sed "s/^${arch}://")
  actual=$(echo "$ACTUAL" | grep "^${agent}|" | cut -d'|' -f3)
  report "$agent ($arch)" "$expected" "$actual"
done <<'EOF'
SAGE|validation
SCOUT|exploration
IMPLEMENTER|build
MAVERICK|innovation
VETERAN|learning
GATEKEEPER|feasibility
ARCHITECT|solution
EOF

echo
echo "Pass: $pass  Fail: $fail"
exit $((fail == 0 ? 0 : 1))
