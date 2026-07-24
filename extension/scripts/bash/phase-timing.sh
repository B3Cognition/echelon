#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/python-detect.sh"

usage() {
  cat >&2 <<'USAGE'
usage:
  phase-timing.sh start_phase <phase_key> <budget_seconds> [--run-dir <path>|--state-file <path>]
  phase-timing.sh end_phase <phase_key> [--run-dir <path>|--state-file <path>]
  phase-timing.sh record_split_metrics <rework_count> <fallback_count> <qa_coverage> [--run-dir <path>|--state-file <path>]

`--state-file` is retained only for compatibility. Its parent directory is the
run directory; this command never reads or writes controller state.
USAGE
}

resolve_run_dir() {
  local explicit="$1" state_file="$2" current root run_id
  if [[ -n "$explicit" ]]; then
    printf '%s\n' "$explicit"
    return 0
  fi
  if [[ -n "$state_file" ]]; then
    dirname "$state_file"
    return 0
  fi
  root="$SCRIPT_DIR"
  while [[ "$root" != "/" ]]; do
    current="$root/runs/.current"
    if [[ -f "$current" ]]; then
      run_id=$(tr -d '[:space:]' < "$current")
      if [[ -n "$run_id" && -d "$root/runs/$run_id" ]]; then
        printf '%s\n' "$root/runs/$run_id"
        return 0
      fi
    fi
    root=$(dirname "$root")
  done
  return 1
}

resolve_echelon_python() {
  local candidate
  for candidate in "$PYTHON" "$HOME/.echelon/venv/bin/python" python3 python; do
    if [[ -n "$candidate" ]] && "$candidate" -c 'import echelon.telemetry.phase_timing' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

[[ $# -ge 2 ]] || { usage; exit 64; }
command="$1"
shift
run_dir=""
state_file=""

case "$command" in
  start_phase)
    [[ $# -ge 2 ]] || { usage; exit 64; }
    phase="$1"
    budget="$2"
    shift 2
    positional=("start_phase" "$phase" "$budget")
    ;;
  end_phase)
    phase="$1"
    shift
    positional=("end_phase" "$phase")
    ;;
  record_split_metrics)
    [[ $# -ge 3 ]] || { usage; exit 64; }
    rework="$1"
    fallback="$2"
    coverage="$3"
    shift 3
    positional=("record_split_metrics" "$rework" "$fallback" "$coverage")
    ;;
  *)
    usage
    exit 64
    ;;
esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir)
      shift
      run_dir="${1:-}"
      ;;
    --state-file)
      shift
      state_file="${1:-}"
      ;;
    --journal-file|--run-id)
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 64
      ;;
  esac
  shift
done

run_dir="$(resolve_run_dir "$run_dir" "$state_file")" || {
  echo "phase timing diagnostic: active run directory is unavailable" >&2
  exit 0
}
telemetry_python="$(resolve_echelon_python)" || {
  echo "phase timing diagnostic: no Python interpreter can import Echelon telemetry" >&2
  exit 0
}
exec "$telemetry_python" -m echelon.telemetry.phase_timing "${positional[@]}" --run-dir "$run_dir"
