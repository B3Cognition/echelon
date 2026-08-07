#!/usr/bin/env bash
# sandbox-exec.sh — Routes commands to sandbox or host
#
# Usage: sandbox-exec.sh <command> [--cwd <dir>] [--timeout <ms>] [--env KEY=VAL...]
#
# Returns: JSON ExecResult on stdout
# Exit code: mirrors the ExecResult.exit_code
#
# Two distinct code paths (FR-FALLBACK-FAILED-002):
#   Path 1 (FR-FALLBACK-ABSENT): harness not installed -> transparent host exec
#   Path 2 (FR-FALLBACK-FAILED-001): harness installed but sandbox unavailable -> hard error
#
# Performance contract (FR-SHIM-001):
#   Routing overhead: < 50ms
#   Routing timeout: 5000ms -> exit 124

set -euo pipefail

# --- Portable timeout ---
# macOS doesn't have `timeout` by default (it's `gtimeout` from coreutils)
_timeout_cmd() {
    if command -v timeout >/dev/null 2>&1; then
        timeout "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$@"
    else
        # No timeout available — run without it
        shift  # skip the timeout duration arg
        "$@"
    fi
}

# --- Configuration ---
ROUTING_TIMEOUT_MS=5000
BUFFER_LIMIT_BYTES="${HARNESS_BUFFER_LIMIT:-10485760}"  # 10MB default
HARNESS_MANIFEST=".specify/extensions/harness/manifest.json"

# --- Detection logic ---

_harness_installed() {
    # Check for harness extension registration file
    # NOT exception-based — explicit file check (FR-FALLBACK-ABSENT)
    [ -f "${HARNESS_MANIFEST}" ]
}

_sandbox_available() {
    # Check Docker is running + sandbox container exists
    [ -n "${HARNESS_SANDBOX_ID:-}" ] && \
    docker info >/dev/null 2>&1 && \
    docker inspect "${HARNESS_SANDBOX_ID}" >/dev/null 2>&1
}

# --- JSON output helpers ---

_json_escape() {
    # Escape a string for JSON embedding
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

_emit_exec_result() {
    local exit_code="$1"
    local stdout_content="$2"
    local stderr_content="$3"
    local duration_ms="$4"
    local truncated="${5:-false}"
    local resource_stats="${6:-null}"

    local escaped_stdout
    escaped_stdout="$(_json_escape "$stdout_content")"
    local escaped_stderr
    escaped_stderr="$(_json_escape "$stderr_content")"

    cat <<EOJSON
{"exit_code":${exit_code},"stdout":"${escaped_stdout}","stderr":"${escaped_stderr}","duration_ms":${duration_ms},"resource_stats":${resource_stats},"truncated":${truncated}}
EOJSON
}

# --- Host execution (Path 1: FR-FALLBACK-ABSENT) ---

_exec_on_host() {
    local cmd="$1"
    local cwd="${2:-.}"
    local timeout_s="$3"

    local start_ms
    start_ms="$(_now_ms)"

    local stdout_file stderr_file
    stdout_file="$(mktemp)"
    stderr_file="$(mktemp)"

    local exit_code=0

    if [ "${timeout_s}" -gt 0 ] 2>/dev/null; then
        _timeout_cmd "${timeout_s}" bash -c "cd '${cwd}' && ${cmd}" \
            >"${stdout_file}" 2>"${stderr_file}" || exit_code=$?
    else
        bash -c "cd '${cwd}' && ${cmd}" \
            >"${stdout_file}" 2>"${stderr_file}" || exit_code=$?
    fi

    local end_ms
    end_ms="$(_now_ms)"
    local duration_ms=$(( end_ms - start_ms ))

    local stdout_content stderr_content truncated
    truncated="false"

    # Apply buffer limit
    local stdout_size stderr_size
    stdout_size="$(wc -c < "${stdout_file}" | tr -d ' ')"
    stderr_size="$(wc -c < "${stderr_file}" | tr -d ' ')"

    if [ "${stdout_size}" -gt "${BUFFER_LIMIT_BYTES}" ]; then
        # Tail-preserving truncation (keep last 80%)
        local tail_size=$(( BUFFER_LIMIT_BYTES * 80 / 100 ))
        stdout_content="[TRUNCATED: ${stdout_size}B]
$(tail -c "${tail_size}" "${stdout_file}")"
        truncated="true"
    else
        stdout_content="$(cat "${stdout_file}")"
    fi

    if [ "${stderr_size}" -gt "${BUFFER_LIMIT_BYTES}" ]; then
        local tail_size=$(( BUFFER_LIMIT_BYTES * 80 / 100 ))
        stderr_content="[TRUNCATED: ${stderr_size}B]
$(tail -c "${tail_size}" "${stderr_file}")"
        truncated="true"
    else
        stderr_content="$(cat "${stderr_file}")"
    fi

    rm -f "${stdout_file}" "${stderr_file}"

    _emit_exec_result "${exit_code}" "${stdout_content}" "${stderr_content}" \
        "${duration_ms}" "${truncated}" "null"

    return "${exit_code}"
}

# --- Sandbox execution (Path 2: FR-FALLBACK-FAILED-001 / routing) ---

_exec_in_sandbox() {
    local cmd="$1"
    local cwd="${2:-${HARNESS_WORKDIR:-/workspace}}"
    local timeout_ms="$3"

    local timeout_s=$(( timeout_ms / 1000 ))
    [ "${timeout_s}" -lt 1 ] && timeout_s=1

    local start_ms
    start_ms="$(_now_ms)"

    local stdout_file stderr_file
    stdout_file="$(mktemp)"
    stderr_file="$(mktemp)"

    local exit_code=0

    _timeout_cmd "${timeout_s}" docker exec \
        --workdir "${cwd}" \
        "${HARNESS_SANDBOX_ID}" \
        sh -c "${cmd}" \
        >"${stdout_file}" 2>"${stderr_file}" || exit_code=$?

    local end_ms
    end_ms="$(_now_ms)"
    local duration_ms=$(( end_ms - start_ms ))

    # Handle timeout exit code
    if [ "${exit_code}" -eq 124 ]; then
        rm -f "${stdout_file}" "${stderr_file}"
        _emit_exec_result 124 "" "Process timed out after ${timeout_ms}ms" \
            "${duration_ms}" "false" "null"
        return 124
    fi

    local stdout_content stderr_content truncated
    truncated="false"

    local stdout_size stderr_size
    stdout_size="$(wc -c < "${stdout_file}" | tr -d ' ')"
    stderr_size="$(wc -c < "${stderr_file}" | tr -d ' ')"

    if [ "${stdout_size}" -gt "${BUFFER_LIMIT_BYTES}" ]; then
        local tail_size=$(( BUFFER_LIMIT_BYTES * 80 / 100 ))
        stdout_content="[TRUNCATED: ${stdout_size}B]
$(tail -c "${tail_size}" "${stdout_file}")"
        truncated="true"
    else
        stdout_content="$(cat "${stdout_file}")"
    fi

    if [ "${stderr_size}" -gt "${BUFFER_LIMIT_BYTES}" ]; then
        local tail_size=$(( BUFFER_LIMIT_BYTES * 80 / 100 ))
        stderr_content="[TRUNCATED: ${stderr_size}B]
$(tail -c "${tail_size}" "${stderr_file}")"
        truncated="true"
    else
        stderr_content="$(cat "${stderr_file}")"
    fi

    rm -f "${stdout_file}" "${stderr_file}"

    # Collect resource stats if possible
    local resource_stats="null"
    if docker stats --no-stream --format '{{json .}}' "${HARNESS_SANDBOX_ID}" >/dev/null 2>&1; then
        local stats_json
        stats_json="$(docker stats --no-stream --format '{{json .}}' "${HARNESS_SANDBOX_ID}" 2>/dev/null || true)"
        if [ -n "${stats_json}" ]; then
            resource_stats="{\"peak_memory_bytes\":0,\"cpu_time_ms\":0,\"wall_time_ms\":${duration_ms}}"
        fi
    fi

    _emit_exec_result "${exit_code}" "${stdout_content}" "${stderr_content}" \
        "${duration_ms}" "${truncated}" "${resource_stats}"

    return "${exit_code}"
}

# --- Time helper ---

_now_ms() {
    # Get current time in milliseconds
    if command -v gdate >/dev/null 2>&1; then
        gdate +%s%3N
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c 'import time; print(int(time.time() * 1000))'
    else
        # Fallback: seconds * 1000
        echo $(( $(date +%s) * 1000 ))
    fi
}

# --- Main entry point ---

sandbox_exec() {
    local cmd=""
    local cwd=""
    local timeout_ms=1200000  # 20 minutes default
    local -a extra_env=()

    # Parse arguments
    while [ $# -gt 0 ]; do
        case "$1" in
            --cwd)
                cwd="$2"
                shift 2
                ;;
            --timeout)
                timeout_ms="$2"
                shift 2
                ;;
            --env)
                extra_env+=("$2")
                shift 2
                ;;
            *)
                if [ -z "${cmd}" ]; then
                    cmd="$1"
                else
                    cmd="${cmd} $1"
                fi
                shift
                ;;
        esac
    done

    if [ -z "${cmd}" ]; then
        echo '{"exit_code":1,"stdout":"","stderr":"sandbox_exec: no command provided","duration_ms":0,"resource_stats":null,"truncated":false}' >&2
        return 1
    fi

    # Export extra env vars
    for env_pair in "${extra_env[@]+"${extra_env[@]}"}"; do
        export "${env_pair?}"
    done

    # Path 1: Harness not installed -> transparent host execution
    if ! _harness_installed; then
        local timeout_s=$(( timeout_ms / 1000 ))
        _exec_on_host "${cmd}" "${cwd:-.}" "${timeout_s}"
        return $?
    fi

    # Path 2: Harness installed but sandbox unavailable -> hard error
    if ! _sandbox_available; then
        echo '{"exit_code":1,"stdout":"","stderr":"sandbox_exec: harness installed but sandbox unavailable. Docker may not be running or HARNESS_SANDBOX_ID is not set.","duration_ms":0,"resource_stats":null,"truncated":false}' >&2
        return 1
    fi

    # Route to sandbox with routing timeout
    local routing_timeout_s=$(( ROUTING_TIMEOUT_MS / 1000 ))
    [ "${routing_timeout_s}" -lt 1 ] && routing_timeout_s=5

    # Check that we can reach the sandbox within routing timeout
    local route_start
    route_start="$(_now_ms)"

    if ! _timeout_cmd "${routing_timeout_s}" docker exec "${HARNESS_SANDBOX_ID}" true >/dev/null 2>&1; then
        local route_end
        route_end="$(_now_ms)"
        local route_duration=$(( route_end - route_start ))

        if [ "${route_duration}" -ge "${ROUTING_TIMEOUT_MS}" ]; then
            _emit_exec_result 124 "" "shim routing timeout (${ROUTING_TIMEOUT_MS}ms)" \
                "${route_duration}" "false" "null"
            return 124
        fi

        echo '{"exit_code":1,"stdout":"","stderr":"sandbox_exec: cannot reach sandbox container","duration_ms":0,"resource_stats":null,"truncated":false}' >&2
        return 1
    fi

    _exec_in_sandbox "${cmd}" "${cwd}" "${timeout_ms}"
    return $?
}

# If sourced, just define functions. If executed, run sandbox_exec.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    sandbox_exec "$@"
fi
