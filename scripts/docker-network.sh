#!/usr/bin/env bash
# docker-network.sh — Network setup: internal Docker network + Squid proxy sidecar.
#
# Per ADR-003: Squid forward proxy on internal Docker network.
# Per FR-NETWORK-001a: default deny-all except allowlist.
# Per FR-OS-001: works on both macOS and Linux.
#
# Usage:
#   source docker-network.sh
#   create_harness_network <network_name>
#   start_squid_proxy <network_name> <proxy_image> <squid_conf_path> \
#       <strategy_id> <spec_id> <run_id>
#   teardown_network <network_name> [proxy_container_id]

set -euo pipefail

readonly LABEL_PREFIX="spec-kit-harness"

# --- create_harness_network ---
# Creates an internal Docker network (no default gateway egress).
#
# Arguments:
#   $1  network_name  Name for the Docker network
#
# Outputs:
#   Network ID on stdout
create_harness_network() {
    local network_name="${1:?network_name required}"

    # --internal prevents default gateway egress; proxy is the only outbound path
    local network_id
    network_id=$(docker network create \
        --internal \
        --label "${LABEL_PREFIX}.type=harness-network" \
        "${network_name}")

    echo "${network_id}"
}

# --- start_squid_proxy ---
# Starts a Squid proxy sidecar on the internal network.
#
# Arguments:
#   $1  network_name    Docker network to connect to
#   $2  proxy_image     Squid Docker image (e.g., ubuntu/squid:latest)
#   $3  squid_conf_path Host path to squid.conf file
#   $4  strategy_id     Label: strategy identifier
#   $5  spec_id         Label: spec identifier
#   $6  run_id          Label: run identifier
#
# Outputs:
#   Proxy container ID on stdout
start_squid_proxy() {
    local network_name="${1:?network_name required}"
    local proxy_image="${2:?proxy_image required}"
    local squid_conf_path="${3:?squid_conf_path required}"
    local strategy_id="${4:?strategy_id required}"
    local spec_id="${5:?spec_id required}"
    local run_id="${6:?run_id required}"

    local proxy_id
    proxy_id=$(docker run -d \
        --network "${network_name}" \
        --name "harness-proxy-${run_id}-$(date +%s)" \
        --volume "${squid_conf_path}:/etc/squid/squid.conf:ro" \
        --label "${LABEL_PREFIX}.type=squid-proxy" \
        --label "${LABEL_PREFIX}.strategy_id=${strategy_id}" \
        --label "${LABEL_PREFIX}.spec_id=${spec_id}" \
        --label "${LABEL_PREFIX}.run_id=${run_id}" \
        "${proxy_image}")

    echo "${proxy_id}"
}

# --- teardown_network ---
# Removes the proxy container and Docker network.
#
# Arguments:
#   $1  network_name         Docker network name
#   $2  proxy_container_id   Proxy container ID (optional)
teardown_network() {
    local network_name="${1:?network_name required}"
    local proxy_container_id="${2:-}"

    # Remove proxy container first (if provided)
    if [[ -n "${proxy_container_id}" ]]; then
        docker rm -f "${proxy_container_id}" > /dev/null 2>&1 || {
            echo "Warning: failed to remove proxy container ${proxy_container_id}" >&2
        }
    fi

    # Remove network (will fail if containers still connected)
    docker network rm "${network_name}" > /dev/null 2>&1 || {
        echo "Warning: failed to remove network ${network_name}" >&2
        return 1
    }
}
