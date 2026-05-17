#!/usr/bin/env bash
# echelon-config-get.sh — Read a single config value from the echelon resolver.
#
# Usage:
#   echelon-config-get.sh <dotted.key.path>
#   echelon-config-get.sh --env <dotted.key.path>   (ECHELON_CFG_* pairs, for bash callers)
#
# Examples:
#   echelon-config-get.sh analysis.token_budget_k        → 999999
#   echelon-config-get.sh endocrine.baselines.exploration → [0.3, 0.7]
#   echelon-config-get.sh --env endocrine.circuit_breakers
#       → ECHELON_CFG_ENDOCRINE_CIRCUIT_BREAKERS_CEILING=0.9
#         ECHELON_CFG_ENDOCRINE_CIRCUIT_BREAKERS_FLOOR=0.1
#
# Repo root is auto-detected by walking up from cwd until .specify/ is found.
# Falls back to reading .specify/extensions/echelon/echelon-config.yml directly
# when specify is unavailable.
#
# Exit codes:
#   0  key found and printed
#   1  key not found or repo root not detected

set -euo pipefail

# ─── argument parsing ────────────────────────────────────────────────────────

ENV_MODE=false
KEY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_MODE=true; shift ;;
    --help|-h)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      if [[ -z "$KEY" ]]; then KEY="$1"; else
        echo "echelon-config-get: unexpected argument: $1" >&2; exit 1
      fi
      shift ;;
  esac
done

if [[ -z "$KEY" ]]; then
  echo "echelon-config-get: key argument required" >&2
  exit 1
fi

# ─── repo root detection ─────────────────────────────────────────────────────

_find_repo_root() {
  local dir
  dir="$(pwd)"
  while [[ "$dir" != "/" ]]; do
    if [[ -d "$dir/.specify" ]]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

REPO_ROOT=""
if ! REPO_ROOT="$(_find_repo_root)"; then
  echo "echelon-config-get: could not find repo root (.specify/ not found in any parent)" >&2
  exit 1
fi

# ─── config resolution ───────────────────────────────────────────────────────

_SPECIFY_BIN=""
if command -v specify &>/dev/null; then
  _SPECIFY_BIN="specify"
fi

_get_json() {
  # Try the specify resolver first, but only trust its output if it actually
  # returned a JSON object. The naive `if [[ -n "$_SPECIFY_BIN" ]]; then specify…`
  # pattern wrongly accepted empty output on installs where
  # `specify extension config resolve` exits non-zero (subcommand missing) —
  # exactly the same failure mode commit df99b73 fixed in endocrine.sh's
  # bootstrap. When the resolver fails, fall through to the YAML fallback.
  if [[ -n "$_SPECIFY_BIN" ]]; then
    local _out
    _out="$(cd "$REPO_ROOT" && "$_SPECIFY_BIN" extension config resolve echelon 2>/dev/null)" || true
    if [[ -n "$_out" && "$_out" =~ ^[[:space:]]*\{ ]]; then
      echo "$_out"
      return 0
    fi
  fi
  # Fallback: read project config file directly (no layer merging).
  # Prefer the deployed config, then fall through to the source config so
  # CI checkouts (where .specify/extensions/ is gitignored) still work.
  local cfg=""
  if [[ -f "$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml" ]]; then
    cfg="$REPO_ROOT/.specify/extensions/echelon/echelon-config.yml"
  elif [[ -f "$REPO_ROOT/extension/echelon-config.yml" ]]; then
    cfg="$REPO_ROOT/extension/echelon-config.yml"
  else
    echo "echelon-config-get: specify resolver failed and no config file found" >&2
    return 1
  fi
  python3 -c "import sys, yaml, json; print(json.dumps(yaml.safe_load(open('$cfg')) or {}))"
}

# ─── key navigation and output ───────────────────────────────────────────────

_JSON=""
if ! _JSON="$(_get_json)"; then
  exit 1
fi

if [[ "$ENV_MODE" == "true" ]]; then
  _ECHELON_JSON="$_JSON" _ECHELON_KEY="$KEY" python3 -c '
import sys, json, os

key_path = os.environ["_ECHELON_KEY"]
data     = json.loads(os.environ["_ECHELON_JSON"])

parts = key_path.split(".")
node  = data
for part in parts:
    if not isinstance(node, dict) or part not in node:
        print(f"echelon-config-get: key \"{key_path}\" not found", file=sys.stderr)
        sys.exit(1)
    node = node[part]

if not isinstance(node, dict):
    print(f"echelon-config-get: --env requires a dict node; \"{key_path}\" is {type(node).__name__}", file=sys.stderr)
    sys.exit(1)

prefix = "ECHELON_CFG_" + key_path.upper().replace(".", "_") + "_"
for k, v in node.items():
    env_key = prefix + k.upper()
    env_val = json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else (str(v) if v is not None else "")
    print(f"{env_key}={env_val}")
'
else
  _ECHELON_JSON="$_JSON" _ECHELON_KEY="$KEY" python3 -c '
import sys, json, os

key_path = os.environ["_ECHELON_KEY"]
data     = json.loads(os.environ["_ECHELON_JSON"])

parts = key_path.split(".")
node  = data
for part in parts:
    if not isinstance(node, dict) or part not in node:
        print(f"echelon-config-get: key \"{key_path}\" not found", file=sys.stderr)
        sys.exit(1)
    node = node[part]

if isinstance(node, (dict, list)):
    print(json.dumps(node, separators=(",", ":")))
elif node is None:
    print("")
elif isinstance(node, bool):
    # YAML/shell convention: lowercase "true"/"false" — not Python repr ("True"/"False").
    # Consumers like validate-deploy.sh compare against the lowercase form.
    print("true" if node else "false")
else:
    print(node)
'
fi
