#!/usr/bin/env bash
# Shared runtime resolution for Echelon-managed Node tools.
# Source this file, then call one of the echelon_resolve_* functions with the
# deployed extension's scripts/node directory.

echelon_codegraph_runtime_ready() {
  local runtime_dir="$1"
  [ -f "$runtime_dir/codegraph-bridge.js" ] &&
    [ -f "$runtime_dir/codegraph-adapter.js" ] &&
    [ -f "$runtime_dir/node_modules/@colbymchenry/codegraph/package.json" ] &&
    node -e '
      const contract = require(process.argv[1]).echelon_runtime;
      process.exit(contract?.provider_artifact_schema_version === 2 &&
        contract?.exact_relationship_endpoints === true &&
        contract?.uncapped_symbols === true ? 0 : 1);
    ' "$runtime_dir/package.json" 2>/dev/null
}

echelon_perlgraph_runtime_ready() {
  local runtime_dir="$1"
  [ -x "$runtime_dir/dist/cli/perlgraph.js" ] &&
    [ -d "$runtime_dir/node_modules" ]
}

echelon_context7_runtime_ready() {
  local runtime_dir="$1"
  [ -x "$runtime_dir/node_modules/.bin/ctx7" ]
}

_echelon_resolve_node_runtime() {
  local tool_name="$1"
  local tool_dir="$2"
  local override_name="$3"
  local local_node_root="$4"
  local ready_function="$5"
  local override_value=""
  local local_runtime="$local_node_root/$tool_dir"
  local shared_runtime="${ECHELON_HOME:-$HOME/.echelon}/node/$tool_dir"

  override_value="${!override_name-}"
  if [ -n "$override_value" ]; then
    if "$ready_function" "$override_value"; then
      printf '%s\n' "$override_value"
      return 0
    fi
    echo "$tool_name runtime override $override_name is incomplete: $override_value" >&2
    echo "Rerun Echelon's installer or correct the explicit override." >&2
    return 1
  fi

  if "$ready_function" "$local_runtime"; then
    printf '%s\n' "$local_runtime"
    return 0
  fi
  if "$ready_function" "$shared_runtime"; then
    printf '%s\n' "$shared_runtime"
    return 0
  fi

  echo "$tool_name runtime is unavailable." >&2
  echo "Checked local runtime: $local_runtime" >&2
  echo "Checked shared runtime: $shared_runtime" >&2
  echo "Run Echelon's installer: bash <echelon-checkout>/scripts/install.sh" >&2
  return 1
}

echelon_resolve_codegraph_runtime() {
  _echelon_resolve_node_runtime \
    "CodeGraph" "codegraph" "ECHELON_CODEGRAPH_RUNTIME_DIR" "$1" \
    echelon_codegraph_runtime_ready
}

echelon_resolve_perlgraph_runtime() {
  _echelon_resolve_node_runtime \
    "PerlGraph" "perlgraph" "ECHELON_PERLGRAPH_RUNTIME_DIR" "$1" \
    echelon_perlgraph_runtime_ready
}

echelon_resolve_context7_runtime() {
  _echelon_resolve_node_runtime \
    "Context7" "context7" "ECHELON_CONTEXT7_RUNTIME_DIR" "$1" \
    echelon_context7_runtime_ready
}
