#!/usr/bin/env bash
# generate-squid-conf.sh — Generate squid.conf from template + config allowlist.
#
# Reads the squid.conf.template and injects additional FQDNs from config.yml
# allowlist. On macOS: proxy-only (no iptables). On Linux: proxy + optional
# iptables for defense-in-depth (ADR-003).
#
# Usage:
#   generate-squid-conf.sh <template_path> <output_path> [additional_fqdns...]
#
# Arguments:
#   $1  template_path    Path to squid.conf.template
#   $2  output_path      Path to write generated squid.conf
#   $3+ additional_fqdns Additional FQDNs to allowlist (from config.yml)
#
# Example:
#   generate-squid-conf.sh network/squid.conf.template /tmp/squid.conf \
#       custom.registry.io internal.nexus.corp.com

set -euo pipefail

readonly TEMPLATE_PATH="${1:?template_path required}"
readonly OUTPUT_PATH="${2:?output_path required}"
shift 2
# Collect remaining args safely (empty array OK with nounset)
ADDITIONAL_FQDNS=()
if [[ $# -gt 0 ]]; then
    ADDITIONAL_FQDNS=("$@")
fi

# Validate template exists
if [[ ! -f "${TEMPLATE_PATH}" ]]; then
    echo "Error: template not found: ${TEMPLATE_PATH}" >&2
    exit 1
fi

# Build the additional allowlist ACL lines into a temp file
acl_file=$(mktemp)
trap 'rm -f "${acl_file}"' EXIT

for fqdn in "${ADDITIONAL_FQDNS[@]+"${ADDITIONAL_FQDNS[@]}"}"; do
    # Skip empty entries
    [[ -z "${fqdn}" ]] && continue
    # Validate FQDN format (basic: alphanumeric, dots, hyphens)
    if [[ ! "${fqdn}" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]]; then
        echo "Warning: skipping invalid FQDN: ${fqdn}" >&2
        continue
    fi
    echo "acl allowlist dstdomain ${fqdn}" >> "${acl_file}"
done

# Generate squid.conf: read template, replace placeholder with file contents
# Use awk for portable multi-line replacement (works on both GNU and BSD)
awk -v acl_file="${acl_file}" '
/# \{\{ADDITIONAL_ALLOWLIST\}\}/ {
    while ((getline line < acl_file) > 0) {
        print line
    }
    next
}
{ print }
' "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"

# Platform-specific defense-in-depth (ADR-003)
case "$(uname -s)" in
    Linux)
        echo "# Platform: Linux — proxy + optional iptables defense-in-depth" >> "${OUTPUT_PATH}"
        echo "# To enable iptables rules, run:" >> "${OUTPUT_PATH}"
        echo "#   iptables -A OUTPUT -m owner --uid-owner sandbox -j DROP" >> "${OUTPUT_PATH}"
        echo "#   iptables -A OUTPUT -m owner --uid-owner sandbox -d 127.0.0.0/8 -j ACCEPT" >> "${OUTPUT_PATH}"
        ;;
    Darwin)
        echo "# Platform: macOS — proxy-only enforcement (no iptables)" >> "${OUTPUT_PATH}"
        echo "# Note: programs ignoring proxy env vars can bypass (documented limitation)" >> "${OUTPUT_PATH}"
        ;;
esac

echo "Generated squid.conf at ${OUTPUT_PATH}" >&2
