---
description: Batch-analyze all specs in a directory and produce a summary report with per-spec scores and overall quality assessment.
---

## Role

You are COMMANDER running batch spec quality analysis across a directory of specs. No agent dispatch — this is toolchain-only.

---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Analyze all spec files in a directory using the `understanding` CLI tool. Produces per-spec scores and an aggregate quality report — useful for tracking quality across multiple features or an entire project.

## Execution Steps

### 1. Locate Specs Directory

```bash
SPECS_DIR="${ARGUMENTS:-specs}"

if [ ! -d "$SPECS_DIR" ]; then
  echo "Directory not found: $SPECS_DIR"
  echo "Usage: /echelon.understanding-batch [directory]"
  echo "Default: specs/"
  exit 1
fi

echo "Batch analyzing: $SPECS_DIR"
```

### 2. Build Command Flags

Check extension config for non-default settings:

- If config `basic` is `true`, add `--basic`
- If config `format` is `json`, add `--json`
- If config `format` is `csv`, add `--csv --output batch-results.csv`
- User $ARGUMENTS flags always override config

### 3. Run Batch Analysis

```bash
understanding "$SPECS_DIR" [FLAGS]
```

The tool automatically discovers all `spec.md` files in the directory tree and analyzes each one.

### 4. Interpret Results

For each spec, the tool reports:
- File path
- Overall score (0-1)
- Quality gates pass/fail

Review the batch output and provide:
- **Summary table**: All specs ranked by overall score
- **Worst performers**: Specs scoring below 0.70 overall
- **Common issues**: Patterns that appear across multiple specs (e.g., all specs have low testability)
- **Trend**: If specs follow a numbering convention, note whether quality is improving or declining

### 5. Recommend Actions

Based on the batch results:
- Prioritize specs that fail quality gates for immediate improvement
- Identify systemic issues (e.g., "all specs lack hard constraints" → team training on testability)
- Suggest running `/echelon.understanding-scan` on specific failing specs for detailed analysis

### 6. For CI/CD Integration

```bash
# Validate all specs in CI — exits 1 if any spec fails
understanding specs/ --validate

# CSV export for tracking over time
understanding specs/ --csv --output quality-report.csv

# JSON for dashboard integration
understanding specs/ --json --output quality-report.json
```

## Notes

- Batch processing analyzes each spec independently — no cross-spec analysis
- Processing time scales linearly: ~500ms per spec (enhanced) or ~200ms (basic)
- Use `--csv --output` to build historical quality tracking
