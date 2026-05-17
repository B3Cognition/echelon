#!/usr/bin/env bash
# Extract configuration and infrastructure files
set -euo pipefail

OUTPUT_FILE="${1:-/tmp/configs.json}"

echo "Extracting configs..." >&2

configs=()

# CI/CD - GitHub Actions
for f in .github/workflows/*.yml .github/workflows/*.yaml; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"ci\", \"file\": \"$f\"}")
done

# CI/CD - GitLab, CircleCI
for f in .gitlab-ci.yml .circleci/config.yml; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"ci\", \"file\": \"$f\"}")
done

# CI/CD - Jenkins (including Jenkinsfile-* variants)
for f in Jenkinsfile*; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"ci\", \"file\": \"$f\"}")
done

# CI/CD - AWS CodeBuild
for f in buildspec*.yml buildspec*.yaml; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"ci\", \"file\": \"$f\"}")
done

# Docker - root level
for f in Dockerfile docker-compose.yml docker-compose.yaml; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"docker\", \"file\": \"$f\"}")
done

# Docker - docker/ directory
for f in docker/Dockerfile* docker/*.yml docker/*.yaml; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"docker\", \"file\": \"$f\"}")
done

# Kubernetes
for f in k8s/*.yml k8s/*.yaml kubernetes/*.yml kubernetes/*.yaml; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"kubernetes\", \"file\": \"$f\"}")
done

# Terraform
for f in *.tf terraform/*.tf; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"terraform\", \"file\": \"$f\"}")
done

# Environment files
for f in .env.example .env.sample env.example; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"env\", \"file\": \"$f\"}")
done

# API schemas
for f in openapi.yml openapi.yaml swagger.yml swagger.yaml schema.graphql; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"api_schema\", \"file\": \"$f\"}")
done

# Database
for f in migrations/*.sql db/schema.rb prisma/schema.prisma; do
    [[ -f "$f" ]] && configs+=("{\"type\": \"database\", \"file\": \"$f\"}")
done

# Output JSON
{
    echo "["
    first=true
    for cfg in ${configs[@]+"${configs[@]}"}; do
        $first || echo ","
        first=false
        echo "  $cfg"
    done
    echo "]"
} > "$OUTPUT_FILE"

echo "Configs saved to $OUTPUT_FILE" >&2
