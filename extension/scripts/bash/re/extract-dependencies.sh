#!/usr/bin/env bash
# Extract dependency information from package manifests
set -euo pipefail

# Check jq availability
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

OUTPUT_FILE="${1:-/tmp/dependencies.json}"

echo "Extracting dependencies..." >&2

deps=()

# Node.js
if [[ -f "package.json" ]]; then
    deps+=("$(jq -c '{type: "npm", file: "package.json", dependencies: (.dependencies // {}), devDependencies: (.devDependencies // {})}' package.json 2>/dev/null || echo '{}')")
fi

# Python - requirements.txt in root
if [[ -f "requirements.txt" ]]; then
    # grep may return empty (no non-comment lines) - that's valid, not an error
    reqs_lines=$(grep -v '^#' requirements.txt 2>/dev/null | grep -v '^$' || true)
    if [[ -n "$reqs_lines" ]]; then
        reqs=$(printf '%s\n' "$reqs_lines" | jq -R . | jq -s '.')
    else
        reqs="[]"
    fi
    deps+=("$(jq -n --argjson packages "$reqs" '{type: "pip", file: "requirements.txt", packages: $packages}')")
fi

# Python - requirements/ directory (Django pattern)
if [[ -d "requirements" ]]; then
    for reqfile in requirements/*.txt; do
        if [[ -f "$reqfile" ]]; then
            # grep may return empty - that's valid, not an error
            reqs_lines=$(grep -v '^#' "$reqfile" 2>/dev/null | grep -v '^$' | grep -v '^-r' || true)
            if [[ -n "$reqs_lines" ]]; then
                reqs=$(printf '%s\n' "$reqs_lines" | jq -R . | jq -s '.')
            else
                reqs="[]"
            fi
            deps+=("$(jq -n --arg file "$reqfile" --argjson packages "$reqs" '{type: "pip", file: $file, packages: $packages}')")
        fi
    done
fi

# Python - setup.py (older projects)
if [[ -f "setup.py" ]]; then
    deps+=("{\"type\": \"setuptools\", \"file\": \"setup.py\"}")
fi

# Python - pyproject.toml (modern projects)
if [[ -f "pyproject.toml" ]]; then
    # Extract dependencies from [project.dependencies] or [tool.poetry.dependencies]
    # This handles PEP 621 and Poetry formats
    pyproject_deps="[]"

    # Check if we can parse with Python (more reliable for TOML)
    if command -v python3 &>/dev/null; then
        pyproject_deps=$(python3 -c '
import sys
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("[]")
        sys.exit(0)

try:
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    deps = []
    # PEP 621 format
    if "project" in data and "dependencies" in data["project"]:
        deps.extend(data["project"]["dependencies"])
    # Poetry format
    if "tool" in data and "poetry" in data["tool"] and "dependencies" in data["tool"]["poetry"]:
        for name, spec in data["tool"]["poetry"]["dependencies"].items():
            if name != "python":
                deps.append(name)

    import json
    print(json.dumps(deps))
except Exception as e:
    print("[]")
' 2>/dev/null || echo '[]')
    fi

    deps+=("$(jq -n --argjson packages "$pyproject_deps" '{type: "pyproject", file: "pyproject.toml", packages: $packages}')")
fi

# Go
if [[ -f "go.mod" ]]; then
    deps+=("{\"type\": \"go\", \"file\": \"go.mod\"}")
fi

# Rust
if [[ -f "Cargo.toml" ]]; then
    deps+=("{\"type\": \"cargo\", \"file\": \"Cargo.toml\"}")
fi

# Java/Kotlin - Maven (search subdirectories for multi-module projects)
while IFS= read -r -d '' f; do
    deps+=("$(jq -n --arg file "$f" '{type: "maven", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "pom.xml" -print0 2>/dev/null || true)

# Java/Kotlin - Gradle
if [[ -f "build.gradle" ]]; then
    deps+=("{\"type\": \"gradle\", \"file\": \"build.gradle\"}")
fi
if [[ -f "build.gradle.kts" ]]; then
    deps+=("{\"type\": \"gradle-kts\", \"file\": \"build.gradle.kts\"}")
fi

# Java/Kotlin - Gradle multi-module (search subdirectories)
while IFS= read -r -d '' f; do
    [[ "$f" != "./build.gradle" ]] && deps+=("$(jq -n --arg file "$f" '{type: "gradle", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "build.gradle" -print0 2>/dev/null || true)

while IFS= read -r -d '' f; do
    [[ "$f" != "./build.gradle.kts" ]] && deps+=("$(jq -n --arg file "$f" '{type: "gradle-kts", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "build.gradle.kts" -print0 2>/dev/null || true)

# Perl - cpanfile (modern)
if [[ -f "cpanfile" ]]; then
    deps+=("{\"type\": \"cpan\", \"file\": \"cpanfile\"}")
fi

# Perl - Makefile.PL (ExtUtils::MakeMaker or Module::Install)
if [[ -f "Makefile.PL" ]]; then
    deps+=("{\"type\": \"perl-makemaker\", \"file\": \"Makefile.PL\"}")
fi

# Perl - Build.PL (Module::Build)
if [[ -f "Build.PL" ]]; then
    deps+=("{\"type\": \"perl-build\", \"file\": \"Build.PL\"}")
fi

# Perl - dist.ini (Dist::Zilla)
if [[ -f "dist.ini" ]]; then
    deps+=("{\"type\": \"perl-distzilla\", \"file\": \"dist.ini\"}")
fi

# .NET - Solution files
for f in *.sln; do
    [[ -f "$f" ]] && deps+=("$(jq -n --arg file "$f" '{type: "dotnet-solution", file: $file}')")
done

# .NET - C# project files (NuGet references)
while IFS= read -r -d '' f; do
    deps+=("$(jq -n --arg file "$f" '{type: "nuget", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "*.csproj" -print0 2>/dev/null || true)

# .NET - F# project files
while IFS= read -r -d '' f; do
    deps+=("$(jq -n --arg file "$f" '{type: "nuget", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "*.fsproj" -print0 2>/dev/null || true)

# .NET - packages.config (older NuGet format)
while IFS= read -r -d '' f; do
    deps+=("$(jq -n --arg file "$f" '{type: "nuget-legacy", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "packages.config" -print0 2>/dev/null || true)

# PHP - Composer (search subdirectories)
while IFS= read -r -d '' f; do
    deps+=("$(jq -c --arg file "$f" '{type: "composer", file: $file, require: (.require // {}), "require-dev": (."require-dev" // {})}' "$f" 2>/dev/null || echo '{}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "composer.json" -print0 2>/dev/null || true)

# Delphi - Project files
while IFS= read -r -d '' f; do
    deps+=("$(jq -n --arg file "$f" '{type: "delphi-project", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "*.dproj" -print0 2>/dev/null || true)

# Delphi - Project group files
for f in *.groupproj; do
    [[ -f "$f" ]] && deps+=("$(jq -n --arg file "$f" '{type: "delphi-group", file: $file}')")
done

# Delphi - Package files (.dpk)
while IFS= read -r -d '' f; do
    deps+=("$(jq -n --arg file "$f" '{type: "delphi-package", file: $file}')")
done < <(find . -maxdepth 3 -not -path '*/.*/*' -name "*.dpk" -print0 2>/dev/null || true)

# Output JSON array
{
    echo "["
    first=true
    for dep in ${deps[@]+"${deps[@]}"}; do
        $first || echo ","
        first=false
        echo "  $dep"
    done
    echo "]"
} > "$OUTPUT_FILE"

echo "Dependencies saved to $OUTPUT_FILE" >&2
