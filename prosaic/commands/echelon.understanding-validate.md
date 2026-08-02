---
name: speckit.echelon.understanding-validate
description: Enforce quality gates on spec (exit code 1 on failure)
execution: command
tools: full
invocation: automatic
visibility: user
color: green
model_tier: fast
---
## Role

You are COMMANDER enforcing spec quality gates. Exit code 1 if any gate fails — use this in CI/CD or before proceeding to implementation.

---

## User Input

```text
{{args}}
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Validate the current feature's spec.md against quality gates based on ISO 29148:2018 and IEEE 830-1998. This is a gate check — the spec must pass before proceeding to planning or implementation.

## Quality Gates

Thresholds are loaded from the resolved project configuration at runtime. The
Understanding output displays the effective values. Treat those values as
authoritative and never use a numeric threshold copied into this document.

## Execution Steps

### 1. Locate Spec

```bash
SPEC_PATH="${ARGUMENTS:-}"

if [ -z "$SPEC_PATH" ]; then
  SPECS_DIR="specs"
  if [ -d "$SPECS_DIR" ]; then
    LATEST=$(ls -d "$SPECS_DIR"/[0-9]*/ 2>/dev/null | sort -r | head -1)
    SPEC_PATH="${LATEST}spec.md"
  fi
fi

if [ ! -f "$SPEC_PATH" ]; then
  echo "No spec.md found. Provide a path: /speckit.echelon.understanding-validate path/to/spec.md"
  exit 1
fi
```

### 2. Build Command Flags

Start with `--validate`. Then check extension config:

- If config `basic` is `true`, add `--basic` (18 metrics, faster validation)
- If config `format` is `json`, add `--json` (structured output for CI/CD)
- If config `format` is `csv`, add `--csv` (spreadsheet reporting)
- User {{args}} flags always override config

### 3. Run Validation

```bash
understanding "$SPEC_PATH" --validate [FLAGS]
```

The `--validate` flag enforces quality gates and exits with code 1 if any gate fails.

### 4. Handle Results

**If all gates pass**: Confirm the spec is ready and suggest proceeding to `/speckit.plan` or `/speckit.tasks`.

**If gates fail**:
- List each failed gate with its score vs threshold
- For each failure, provide specific improvement suggestions
- Offer to help rewrite the worst-scoring requirements
- Always preserve validation thresholds; do NOT suggest skipping validation or lowering thresholds

### 5. For CI/CD Integration

```bash
# JSON output for automated pipelines
understanding "$SPEC_PATH" --validate --json

# CSV for spreadsheet reporting
understanding "$SPEC_PATH" --validate --csv --output results.csv
```

## Operating Principles

- **Non-negotiable gates**: Quality gates are based on ISO/IEEE standards — they exist for a reason
- **Actionable feedback**: Every failure must come with a specific fix suggestion
- **No false comfort**: Don't minimize failures or suggest they're "close enough"
