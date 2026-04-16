#!/usr/bin/env bash
# fix-spa-base.sh — auto-correct SPA base/basePath for Traefik path-prefix routing
# Called by deploy-init.sh after state is written.
# Always auto-corrects — never requires manual intervention.
#
# Usage: fix-spa-base.sh <project_root> <app_name>
set -euo pipefail

PROJECT_ROOT="${1:?PROJECT_ROOT required}"
APP_NAME="${2:?APP_NAME required}"
EXPECTED_BASE="/${APP_NAME}/"

_patched=false

# ── Vite ─────────────────────────────────────────────────────────────────────
for ext in js ts mjs cjs; do
  VITE_CONFIG="${PROJECT_ROOT}/vite.config.${ext}"
  [ -f "${VITE_CONFIG}" ] || continue

  RESULT=$(APP_NAME="${APP_NAME}" VITE_CONFIG="${VITE_CONFIG}" python3 - <<'PYEOF'
import os, re

app_name = os.environ['APP_NAME']
path = os.environ['VITE_CONFIG']
expected = f'/{app_name}/'

with open(path) as f:
    content = f.read()

# Already correct?
if re.search(r"""\bbase\s*:\s*['"]""" + re.escape(expected) + r"""['"]""", content):
    print('ok')
    exit(0)

# Literal base: present but wrong value → replace it
lit = re.search(r"""(\bbase\s*:\s*)(['"])([^'"]*)\2""", content)
if lit:
    old_val = lit.group(3)
    new_content = content[:lit.start()] + f"base: '{expected}'" + content[lit.end():]
    with open(path, 'w') as f:
        f.write(new_content)
    print(f'replaced:{old_val}')
    exit(0)

# Dynamic/computed base: present but not a string literal → comment out, insert literal
dyn = re.search(r'([ \t]*)(base\s*:(?!.*#.*echelon).*)', content)
if dyn:
    indent = dyn.group(1)
    old_line = dyn.group(2)
    replacement = (
        f"{indent}// {old_line}  // ← echelon: overridden for path-prefix routing\n"
        f"{indent}base: '{expected}',  // ← echelon: auto-configured"
    )
    new_content = content[:dyn.start()] + replacement + content[dyn.end():]
    with open(path, 'w') as f:
        f.write(new_content)
    print(f'override-dynamic')
    exit(0)

# base: missing entirely → inject after defineConfig({ or export default {
injected = False
for pattern in [
    r'(defineConfig\s*\(\s*\{)',
    r'(export\s+default\s+\{)',
]:
    m = re.search(pattern, content)
    if m:
        insert_pos = m.end()
        new_content = (
            content[:insert_pos]
            + f"\n  base: '{expected}',  // ← echelon: auto-configured for path-prefix routing"
            + content[insert_pos:]
        )
        with open(path, 'w') as f:
            f.write(new_content)
        print('added')
        injected = True
        break

if not injected:
    print('skip:no-defineconfig')
PYEOF
)

  case "${RESULT}" in
    ok)
      echo "deploy: ✓ ${VITE_CONFIG##*/} — base already '${EXPECTED_BASE}'"
      ;;
    replaced:*)
      OLD="${RESULT#replaced:}"
      echo "deploy: ✓ ${VITE_CONFIG##*/} — corrected base '${OLD}' → '${EXPECTED_BASE}'"
      _patched=true
      ;;
    override-dynamic)
      echo "deploy: ✓ ${VITE_CONFIG##*/} — dynamic base overridden with '${EXPECTED_BASE}' (old line commented out)"
      _patched=true
      ;;
    added)
      echo "deploy: ✓ ${VITE_CONFIG##*/} — added base '${EXPECTED_BASE}'"
      _patched=true
      ;;
    skip:*)
      echo "deploy: ⚠ ${VITE_CONFIG##*/} — could not locate defineConfig or export default; base not set"
      echo "     Add manually: base: '${EXPECTED_BASE}'"
      ;;
  esac
  break  # only process the first vite.config found
done

# ── Next.js ───────────────────────────────────────────────────────────────────
for ext in js ts mjs; do
  NEXT_CONFIG="${PROJECT_ROOT}/next.config.${ext}"
  [ -f "${NEXT_CONFIG}" ] || continue

  RESULT=$(APP_NAME="${APP_NAME}" NEXT_CONFIG="${NEXT_CONFIG}" python3 - <<'PYEOF'
import os, re

app_name = os.environ['APP_NAME']
path = os.environ['NEXT_CONFIG']
expected = f'/{app_name}'   # Next.js basePath has no trailing slash

with open(path) as f:
    content = f.read()

# Already correct?
if re.search(r"""\bbasePath\s*:\s*['"]""" + re.escape(expected) + r"""['"]""", content):
    print('ok')
    exit(0)

# Literal basePath: present but wrong → replace
lit = re.search(r"""(\bbasePath\s*:\s*)(['"])([^'"]*)\2""", content)
if lit:
    old_val = lit.group(3)
    new_content = content[:lit.start()] + f"basePath: '{expected}'" + content[lit.end():]
    with open(path, 'w') as f:
        f.write(new_content)
    print(f'replaced:{old_val}')
    exit(0)

# Dynamic basePath → comment out, insert literal
dyn = re.search(r'([ \t]*)(basePath\s*:(?!.*#.*echelon).*)', content)
if dyn:
    indent = dyn.group(1)
    old_line = dyn.group(2)
    replacement = (
        f"{indent}// {old_line}  // ← echelon: overridden for path-prefix routing\n"
        f"{indent}basePath: '{expected}',  // ← echelon: auto-configured"
    )
    new_content = content[:dyn.start()] + replacement + content[dyn.end():]
    with open(path, 'w') as f:
        f.write(new_content)
    print('override-dynamic')
    exit(0)

# Missing → inject into module.exports or export default
for pattern in [r'(module\.exports\s*=\s*\{)', r'(export\s+default\s+\{)']:
    m = re.search(pattern, content)
    if m:
        new_content = (
            content[:m.end()]
            + f"\n  basePath: '{expected}',  // ← echelon: auto-configured for path-prefix routing"
            + content[m.end():]
        )
        with open(path, 'w') as f:
            f.write(new_content)
        print('added')
        exit(0)

print('skip:no-config-object')
PYEOF
)

  case "${RESULT}" in
    ok)       echo "deploy: ✓ ${NEXT_CONFIG##*/} — basePath already '${EXPECTED_BASE%/}'" ;;
    replaced:*) OLD="${RESULT#replaced:}"; echo "deploy: ✓ ${NEXT_CONFIG##*/} — corrected basePath '${OLD}' → '${EXPECTED_BASE%/}'"; _patched=true ;;
    override-dynamic) echo "deploy: ✓ ${NEXT_CONFIG##*/} — dynamic basePath overridden with '${EXPECTED_BASE%/}' (old line commented out)"; _patched=true ;;
    added)    echo "deploy: ✓ ${NEXT_CONFIG##*/} — added basePath '${EXPECTED_BASE%/}'"; _patched=true ;;
    skip:*)   echo "deploy: ⚠ ${NEXT_CONFIG##*/} — could not locate config object; basePath not set" ;;
  esac
  break
done

# ── Create React App (package.json homepage) ──────────────────────────────────
PKG="${PROJECT_ROOT}/package.json"
if [ -f "${PKG}" ] && python3 -c "import json; d=json.load(open('${PKG}')); exit(0 if 'react-scripts' in str(d.get('dependencies',{})) or 'react-scripts' in str(d.get('devDependencies',{})) else 1)" 2>/dev/null; then
  RESULT=$(APP_NAME="${APP_NAME}" PKG="${PKG}" python3 - <<'PYEOF'
import os, json

app_name = os.environ['APP_NAME']
path = os.environ['PKG']
expected = f'/{app_name}'

with open(path) as f:
    d = json.load(f)

current = d.get('homepage', '')
if current == expected:
    print('ok')
    exit(0)

old = current or '(none)'
d['homepage'] = expected
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
print(f'set:{old}')
PYEOF
)

  case "${RESULT}" in
    ok)    echo "deploy: ✓ package.json — homepage already '${EXPECTED_BASE%/}'" ;;
    set:*) OLD="${RESULT#set:}"; echo "deploy: ✓ package.json — set homepage '${OLD}' → '${EXPECTED_BASE%/}'"; _patched=true ;;
  esac
fi

# ── Summary ───────────────────────────────────────────────────────────────────
if [ "${_patched}" = "true" ]; then
  echo ""
  echo "deploy: ⚠ SPA config was auto-corrected for path-prefix routing."
  echo "     Review the changes above and commit them with your next push."
  echo "     Path: http://localhost/${APP_NAME}/"
fi
