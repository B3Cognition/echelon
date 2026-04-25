#!/usr/bin/env bash
# docker-gc.sh — Garbage collection for stale containers and worktrees.
#
# Per FR-GC-001: configurable age thresholds for worktrees (24h),
# containers (1h), and .bak files (7d).
#
# Usage:
#   source docker-gc.sh
#   gc_stale_containers [max_age_hours]
#   gc_stale_worktrees <worktree_dir> [max_age_hours]
#   gc_stale_backups <backup_dir> [max_age_days]

set -euo pipefail

readonly LABEL_PREFIX="spec-kit-harness"
readonly DEFAULT_CONTAINER_MAX_AGE_HOURS=1
readonly DEFAULT_WORKTREE_MAX_AGE_HOURS=24
readonly DEFAULT_BACKUP_MAX_AGE_DAYS=7

# --- gc_stale_containers ---
# Finds and removes harness containers older than the threshold.
#
# Arguments:
#   $1  max_age_hours  Maximum age in hours (default: 1)
#
# Outputs:
#   Removed container IDs, one per line
gc_stale_containers() {
    local max_age_hours="${1:-${DEFAULT_CONTAINER_MAX_AGE_HOURS}}"
    local max_age_seconds=$((max_age_hours * 3600))
    local now_epoch
    now_epoch=$(date +%s)

    # Find containers with our label
    local container_ids
    container_ids=$(docker ps -a \
        --filter "label=${LABEL_PREFIX}.strategy_id" \
        --format '{{.ID}}' 2>/dev/null) || return 0

    if [[ -z "${container_ids}" ]]; then
        return 0
    fi

    while IFS= read -r container_id; do
        [[ -z "${container_id}" ]] && continue

        # Get creation time from label
        local created_at
        created_at=$(docker inspect \
            --format '{{index .Config.Labels "spec-kit-harness.created_at"}}' \
            "${container_id}" 2>/dev/null) || continue

        if [[ -z "${created_at}" ]]; then
            # Fall back to Docker's Created field
            created_at=$(docker inspect \
                --format '{{.Created}}' \
                "${container_id}" 2>/dev/null) || continue
        fi

        # Parse timestamp to epoch (portable: try GNU date then BSD date)
        local created_epoch
        created_epoch=$(date -d "${created_at}" +%s 2>/dev/null) || \
            created_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" \
                "$(echo "${created_at}" | cut -c1-19)" +%s 2>/dev/null) || continue

        local age_seconds=$(( now_epoch - created_epoch ))

        if (( age_seconds > max_age_seconds )); then
            echo "GC: removing stale container ${container_id} (age: $((age_seconds / 3600))h)" >&2
            docker rm -f "${container_id}" > /dev/null 2>&1 || {
                echo "GC: warning: failed to remove ${container_id}" >&2
            }
            echo "${container_id}"
        fi
    done <<< "${container_ids}"
}

# --- gc_stale_worktrees ---
# Finds and removes worktree directories older than the threshold.
#
# Arguments:
#   $1  worktree_dir    Base directory containing worktrees
#   $2  max_age_hours   Maximum age in hours (default: 24)
#
# Outputs:
#   Removed worktree paths, one per line
gc_stale_worktrees() {
    local worktree_dir="${1:?worktree_dir required}"
    local max_age_hours="${2:-${DEFAULT_WORKTREE_MAX_AGE_HOURS}}"

    if [[ ! -d "${worktree_dir}" ]]; then
        return 0
    fi

    # Find directories by mtime older than threshold
    # Using -mmin for minute-level granularity
    local max_age_minutes=$((max_age_hours * 60))

    while IFS= read -r worktree_path; do
        [[ -z "${worktree_path}" ]] && continue
        echo "GC: removing stale worktree ${worktree_path} (older than ${max_age_hours}h)" >&2
        rm -rf "${worktree_path}" || {
            echo "GC: warning: failed to remove ${worktree_path}" >&2
        }
        echo "${worktree_path}"
    done < <(find "${worktree_dir}" -maxdepth 1 -mindepth 1 -type d -mmin "+${max_age_minutes}" 2>/dev/null)
}

# --- gc_stale_backups ---
# Finds and removes .bak files older than the threshold.
#
# Arguments:
#   $1  backup_dir      Directory containing .bak files
#   $2  max_age_days    Maximum age in days (default: 7)
#
# Outputs:
#   Removed backup file paths, one per line
gc_stale_backups() {
    local backup_dir="${1:?backup_dir required}"
    local max_age_days="${2:-${DEFAULT_BACKUP_MAX_AGE_DAYS}}"

    if [[ ! -d "${backup_dir}" ]]; then
        return 0
    fi

    while IFS= read -r backup_file; do
        [[ -z "${backup_file}" ]] && continue
        echo "GC: removing stale backup ${backup_file} (older than ${max_age_days}d)" >&2
        rm -f "${backup_file}" || {
            echo "GC: warning: failed to remove ${backup_file}" >&2
        }
        echo "${backup_file}"
    done < <(find "${backup_dir}" -name "*.bak" -type f -mtime "+${max_age_days}" 2>/dev/null)
}
