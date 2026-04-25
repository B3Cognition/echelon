#!/usr/bin/env bash
# docker-sandbox.sh — Docker container lifecycle: create, exec, destroy.
#
# Per ADR-001: shell scripts for Docker CLI interaction layer.
# Per contracts/sandbox-provider.md: resource limits, labels, env injection.
#
# Usage:
#   source docker-sandbox.sh
#   create_sandbox <image> <worktree_mount> <container_mount> \
#       <memory> <cpus> <pids_limit> \
#       <strategy_id> <spec_id> <run_id> \
#       [env_file] [post_create_cmd]
#   exec_in_sandbox <container_id> <cmd> <timeout_seconds> [buffer_limit_bytes]
#   destroy_sandbox <container_id>

set -euo pipefail

# --- Constants ---
readonly LABEL_PREFIX="spec-kit-harness"
readonly DEFAULT_BUFFER_LIMIT=10485760  # 10MB

# --- create_sandbox ---
# Creates a Docker container with resource limits, bind mount, labels, and env.
#
# Arguments:
#   $1  image            Docker image to run
#   $2  worktree_mount   Host path to bind-mount
#   $3  container_mount  Container-side mount path (e.g., /workspace)
#   $4  memory           Memory limit (e.g., "4g")
#   $5  cpus             CPU limit (e.g., "2.0")
#   $6  pids_limit       PID limit (e.g., "256")
#   $7  strategy_id      Label: strategy identifier
#   $8  spec_id          Label: spec identifier
#   $9  run_id           Label: run identifier
#   $10 network_name     Docker network to connect to (optional, "" to skip)
#   $11 env_file         Path to env file (optional, "" to skip)
#   $12 post_create_cmd  Command to run after container start (optional)
#
# Outputs:
#   Container ID on stdout
create_sandbox() {
    local image="${1:?image required}"
    local worktree_mount="${2:?worktree_mount required}"
    local container_mount="${3:?container_mount required}"
    local memory="${4:?memory required}"
    local cpus="${5:?cpus required}"
    local pids_limit="${6:?pids_limit required}"
    local strategy_id="${7:?strategy_id required}"
    local spec_id="${8:?spec_id required}"
    local run_id="${9:?run_id required}"
    local network_name="${10:-}"
    local env_file="${11:-}"
    local post_create_cmd="${12:-}"

    local -a docker_args=(
        "run" "-d"
        "--memory" "${memory}"
        "--cpus" "${cpus}"
        "--pids-limit" "${pids_limit}"
        "--volume" "${worktree_mount}:${container_mount}"
        "--workdir" "${container_mount}"
        "--label" "${LABEL_PREFIX}.strategy_id=${strategy_id}"
        "--label" "${LABEL_PREFIX}.spec_id=${spec_id}"
        "--label" "${LABEL_PREFIX}.run_id=${run_id}"
        "--label" "${LABEL_PREFIX}.created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    )

    # Connect to Docker network if specified
    if [[ -n "${network_name}" ]]; then
        docker_args+=("--network" "${network_name}")
    fi

    # Inject environment variables from file
    if [[ -n "${env_file}" && -f "${env_file}" ]]; then
        docker_args+=("--env-file" "${env_file}")
    fi

    # Keep container running with tail -f /dev/null
    docker_args+=("${image}" "tail" "-f" "/dev/null")

    local container_id
    container_id=$(docker "${docker_args[@]}")

    # Execute post-create command if specified
    if [[ -n "${post_create_cmd}" ]]; then
        docker exec "${container_id}" sh -c "${post_create_cmd}" || {
            echo "Warning: post_create_command failed (exit $?)" >&2
        }
    fi

    echo "${container_id}"
}

# --- exec_in_sandbox ---
# Executes a command inside a running sandbox container.
#
# Arguments:
#   $1  container_id       Docker container ID
#   $2  cmd                Command to execute (passed to sh -c)
#   $3  timeout_seconds    Timeout in seconds
#   $4  buffer_limit_bytes Maximum bytes to capture (default: 10MB)
#   $5  cwd                Working directory inside container (optional)
#
# Outputs:
#   stdout and stderr are captured with size limits.
#   Exit code is returned (124 for timeout per FR-SANDBOX-003a).
exec_in_sandbox() {
    local container_id="${1:?container_id required}"
    local cmd="${2:?cmd required}"
    local timeout_seconds="${3:?timeout_seconds required}"
    local buffer_limit_bytes="${4:-${DEFAULT_BUFFER_LIMIT}}"
    local cwd="${5:-}"

    local -a exec_args=("exec")

    if [[ -n "${cwd}" ]]; then
        exec_args+=("--workdir" "${cwd}")
    fi

    exec_args+=("${container_id}" "sh" "-c" "${cmd}")

    local exit_code=0
    local stdout_file stderr_file
    stdout_file=$(mktemp)
    stderr_file=$(mktemp)

    # Use timeout command for enforcement (FR-SANDBOX-003a)
    # --signal=TERM --kill-after=5s implements FR-SANDBOX-003b/c
    timeout --signal=TERM --kill-after=5s "${timeout_seconds}" \
        docker "${exec_args[@]}" \
        > >(head -c "${buffer_limit_bytes}" > "${stdout_file}") \
        2> >(head -c "${buffer_limit_bytes}" > "${stderr_file}") \
        || exit_code=$?

    # Output captured content
    cat "${stdout_file}"
    cat "${stderr_file}" >&2

    # Clean up temp files
    rm -f "${stdout_file}" "${stderr_file}"

    return "${exit_code}"
}

# --- destroy_sandbox ---
# Force-removes a Docker container. Does not hang on stuck containers.
#
# Arguments:
#   $1  container_id  Docker container ID
destroy_sandbox() {
    local container_id="${1:?container_id required}"

    # docker rm -f: force remove, no hang on stuck container (FR-SANDBOX-003c)
    docker rm -f "${container_id}" > /dev/null 2>&1 || {
        echo "Warning: failed to remove container ${container_id}" >&2
        return 1
    }
}
