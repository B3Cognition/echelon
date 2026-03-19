#!/usr/bin/env bash
# T037: Test Reporting Infrastructure
# Generates JUnit-compatible XML and a markdown executive summary from test output.
# Usage:
#   bash tests/utils/report-generator.sh [--input <file>] [--output-dir <dir>] [--tier <name>]
# Input: structured test output with lines:
#   PASS: <test_name>
#   FAIL: <test_name> — <reason>
#   Results: N passed, M failed
# Output: tests/reports/<tier>-report.xml and tests/reports/summary.md
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
REPORTS_DIR="$REPO_ROOT/tests/reports"
mkdir -p "$REPORTS_DIR"

input_file=""
output_dir="$REPORTS_DIR"
tier="all"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      shift; input_file="${1:-}"
      ;;
    --output-dir)
      shift; output_dir="${1:-$REPORTS_DIR}"
      ;;
    --tier)
      shift; tier="${1:-all}"
      ;;
    -h|--help)
      cat >&2 <<'USAGE'
usage: report-generator.sh [--input <file>] [--output-dir <dir>] [--tier <name>]

Reads structured test output (from stdin or --input file) and writes:
  <output-dir>/<tier>-report.xml   (JUnit XML)
  <output-dir>/summary.md          (executive markdown summary)

Input format (one result per line):
  PASS: <test_name>
  FAIL: <test_name> — <reason>
  Results: N passed, M failed
USAGE
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 64
      ;;
  esac
  shift
done

mkdir -p "$output_dir"

# Read input from file or stdin
if [[ -n "$input_file" ]]; then
  if [[ ! -f "$input_file" ]]; then
    printf 'report-generator: input file not found: %s\n' "$input_file" >&2
    exit 1
  fi
  test_output="$(cat "$input_file")"
else
  test_output="$(cat)"
fi

# Parse test output using python3
python3 - "$output_dir" "$tier" <<PY
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone

output_dir = Path(sys.argv[1])
tier = sys.argv[2]
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

test_output = """$test_output"""

pass_tests = []
fail_tests = []
total_duration = 0.0

for line in test_output.splitlines():
    line = line.strip()
    if line.startswith("PASS:") or line.startswith("PASS "):
        name = line.split(":", 1)[1].strip() if ":" in line else line.split(" ", 1)[1].strip()
        pass_tests.append({"name": name, "status": "pass"})
    elif line.startswith("FAIL:") or line.startswith("FAIL "):
        rest = line.split(":", 1)[1].strip() if ":" in line else line.split(" ", 1)[1].strip()
        parts = rest.split(" — ", 1)
        name = parts[0].strip()
        reason = parts[1].strip() if len(parts) > 1 else "unknown"
        fail_tests.append({"name": name, "status": "fail", "reason": reason})

total = len(pass_tests) + len(fail_tests)
failed = len(fail_tests)

# Write JUnit XML report
xml_path = output_dir / f"{tier}-report.xml"
xml_lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    f'<testsuite name="{tier}" tests="{total}" failures="{failed}" timestamp="{now}">',
]
for t in pass_tests:
    safe_name = t["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml_lines.append(f'  <testcase name="{safe_name}" classname="{tier}"/>')
for t in fail_tests:
    safe_name = t["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_reason = t["reason"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml_lines.append(f'  <testcase name="{safe_name}" classname="{tier}">')
    xml_lines.append(f'    <failure message="{safe_reason}"/>')
    xml_lines.append("  </testcase>")
xml_lines.append("</testsuite>")
xml_path.write_text("\n".join(xml_lines) + "\n", encoding="utf-8")

# Write/update markdown summary
summary_path = output_dir / "summary.md"
# Read existing summary or start fresh
if summary_path.exists():
    existing = summary_path.read_text(encoding="utf-8")
    # Remove old section for this tier if present
    lines = existing.splitlines()
    new_lines = []
    skip = False
    for line in lines:
        if line.startswith(f"## {tier}"):
            skip = True
        elif skip and line.startswith("## "):
            skip = False
        if not skip:
            new_lines.append(line)
    existing_header = "\n".join(new_lines).strip()
else:
    existing_header = "# Test Suite Summary\n"

tier_section = [
    f"## {tier}",
    f"",
    f"| Metric | Value |",
    f"|--------|-------|",
    f"| Total | {total} |",
    f"| Passed | {len(pass_tests)} |",
    f"| Failed | {failed} |",
    f"| Generated | {now} |",
    f"",
]
if fail_tests:
    tier_section.append("**Failing tests:**")
    for t in fail_tests:
        tier_section.append(f"- `{t['name']}`: {t['reason']}")
    tier_section.append("")

summary_content = existing_header + "\n\n" + "\n".join(tier_section)
summary_path.write_text(summary_content.strip() + "\n", encoding="utf-8")

print(f"Report written: {xml_path}")
print(f"Summary updated: {summary_path}")
print(f"Tier '{tier}': {len(pass_tests)} passed, {failed} failed out of {total} total.")
sys.exit(0 if failed == 0 else 1)
PY

rc=$?
exit $rc
