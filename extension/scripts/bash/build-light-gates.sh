#!/usr/bin/env sh
set -eu
. "$(CDPATH='' cd "$(dirname -- "$0")" && pwd)/python-detect.sh"

usage() {
  cat <<'USAGE' >&2
usage:
  build-light-gates.sh evaluate --task-id <id> --paths <comma_list> --required-outputs <comma_list> [--tests-cmd <command>]
USAGE
}

json_bool() {
  if [ "$1" = "1" ]; then
    printf 'true'
  else
    printf 'false'
  fi
}

check_build_valid() {
  paths_csv="$1"
  [ -z "$paths_csv" ] && return 0
  OLD_IFS="$IFS"
  IFS=','
  for p in $paths_csv; do
    [ -z "$p" ] && continue
    [ ! -f "$p" ] && return 1
    case "$p" in
      *.sh)
        sh -n "$p" >/dev/null 2>&1 || return 1
        ;;
      *.yaml|*.yml)
        if command -v $PYTHON >/dev/null 2>&1; then
          $PYTHON - "$p" <<'PY' >/dev/null 2>&1 || exit 1
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
if ':' not in text:
    raise SystemExit(1)
PY
        else
          grep -q ':' "$p" || return 1
        fi
        ;;
      *)
        ;;
    esac
  done
  IFS="$OLD_IFS"
  return 0
}

check_tests_passed() {
  cmd="$1"
  [ -z "$cmd" ] && return 0
  # Route through sandbox-exec.sh if harness is installed (FR-SHIM-002a)
  SHIM=".specify/extensions/harness/scripts/sandbox-exec.sh"
  if [ -f "$SHIM" ] && [ -f ".specify/extensions/harness/manifest.json" ]; then
    bash "$SHIM" "$cmd" >/dev/null 2>&1
  else
    sh -c "$cmd" >/dev/null 2>&1
  fi
}

check_lint_clean() {
  paths_csv="$1"
  if ! command -v shellcheck >/dev/null 2>&1; then
    return 0
  fi
  [ -z "$paths_csv" ] && return 0
  OLD_IFS="$IFS"
  IFS=','
  for p in $paths_csv; do
    [ -z "$p" ] && continue
    case "$p" in
      *.sh)
        shellcheck "$p" >/dev/null 2>&1 || return 1
        ;;
      *)
        ;;
    esac
  done
  IFS="$OLD_IFS"
  return 0
}

check_required_outputs() {
  outputs_csv="$1"
  [ -z "$outputs_csv" ] && return 0
  OLD_IFS="$IFS"
  IFS=','
  for p in $outputs_csv; do
    [ -z "$p" ] && continue
    [ -f "$p" ] || return 1
  done
  IFS="$OLD_IFS"
  return 0
}

main() {
  [ $# -ge 1 ] || { usage; exit 64; }
  cmd="$1"
  shift

  [ "$cmd" = "evaluate" ] || { usage; exit 64; }

  task_id=""
  paths=""
  required_outputs=""
  tests_cmd=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --task-id)
        shift
        task_id="${1:-}"
        ;;
      --paths)
        shift
        paths="${1:-}"
        ;;
      --required-outputs)
        shift
        required_outputs="${1:-}"
        ;;
      --tests-cmd)
        shift
        tests_cmd="${1:-}"
        ;;
      *)
        usage
        exit 64
        ;;
    esac
    shift
  done

  [ -n "$task_id" ] || { usage; exit 64; }

  build_valid=1
  tests_passed=1
  lint_clean=1
  required_outputs_present=1

  check_build_valid "$paths" || build_valid=0
  check_tests_passed "$tests_cmd" || tests_passed=0
  check_lint_clean "$paths" || lint_clean=0
  check_required_outputs "$required_outputs" || required_outputs_present=0

  fail_reasons=""
  [ "$build_valid" = "1" ] || fail_reasons="build_valid"
  [ "$tests_passed" = "1" ] || fail_reasons="${fail_reasons:+$fail_reasons,}tests_passed"
  [ "$lint_clean" = "1" ] || fail_reasons="${fail_reasons:+$fail_reasons,}lint_clean"
  [ "$required_outputs_present" = "1" ] || fail_reasons="${fail_reasons:+$fail_reasons,}required_outputs_present"

  printf '{\n'
  printf '  "task_id": "%s",\n' "$task_id"
  printf '  "build_valid": %s,\n' "$(json_bool "$build_valid")"
  printf '  "tests_passed": %s,\n' "$(json_bool "$tests_passed")"
  printf '  "lint_clean": %s,\n' "$(json_bool "$lint_clean")"
  printf '  "required_outputs_present": %s,\n' "$(json_bool "$required_outputs_present")"
  printf '  "fail_reasons": "%s"\n' "$fail_reasons"
  printf '}\n'

  [ "$build_valid" = "1" ] && [ "$tests_passed" = "1" ] && [ "$lint_clean" = "1" ] && [ "$required_outputs_present" = "1" ]
}

main "$@"
