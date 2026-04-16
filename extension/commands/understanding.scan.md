---
description: Scan spec for 31 requirements quality metrics across 6 categories (Structure, Testability, Readability, Cognitive, Semantic, Behavioral) with quality gates.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Analyze the current feature's spec.md using the `understanding` CLI tool to produce a requirements quality report with 31 deterministic metrics.

## Prerequisites

The `understanding` CLI tool must be installed:

```bash
uv tool install git+https://github.com/Testimonial/understanding.git --with "spacy>=3.0.0"
```

## Execution Steps

### 1. Locate Spec

Find the spec to analyze:

- If user provided a path in $ARGUMENTS, use that
- Otherwise, find the current feature's spec.md using the spec-kit convention: `specs/NNN-feature-name/spec.md`

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
  echo "No spec.md found. Provide a path: /b3c.understanding.scan path/to/spec.md"
  exit 1
fi

echo "Analyzing: $SPEC_PATH"
```

### 2. Build Command Flags

Check the extension config for non-default settings. Build the flags accordingly:

- If config `basic` is `true`, add `--basic` (18 metrics, no NLP, ~200ms)
- If config `per_req` is `true`, add `--per-req` (per-requirement breakdown)
- If config `energy` is `true`, add `--energy` (token-level ambiguity)
- If config `diagram` is not `false`, add `--diagram <value>` (`text` for ASCII, or a file path)
- If config `format` is `json`, add `--json`
- If config `format` is `csv`, add `--csv`
- User $ARGUMENTS flags always override config

### 3. Run Analysis

```bash
understanding "$SPEC_PATH" [FLAGS]
```

This produces:
- **Overall Score** (0-1) with quality level
- **6 Category Scores**: Structure (30%), Testability (20%), Readability (15%), Cognitive (15%), Semantic (10%), Behavioral (10%)
- **Quality Gates**: Pass/fail against ISO 29148 and IEEE 830 thresholds
- **Entity Analysis**: Actors, actions, and objects extracted from requirements

### 4. Interpret Results

Review the output and provide actionable feedback:

- **Categories below threshold**: Explain what's wrong and how to fix it
- **Semantic < 60%**: Requirements lack explicit actor-action-object patterns. Suggest rewrites with "The system shall [action] [object] when [trigger]"
- **Testability < 70%**: Requirements lack quantifiable constraints. Suggest adding numbers, time limits, error codes
- **Structure < 70%**: Requirements may be compound or use passive voice. Suggest splitting and using active voice
- **Readability < 50%**: Sentences are too complex. Suggest shorter sentences, simpler words
- **Cognitive < 60%**: Too many concepts per sentence. Suggest breaking into smaller requirements

### 5. Summarize

Provide a brief summary:
- Overall pass/fail status
- Top 3 issues to fix for the biggest score improvement
- Specific rewrite suggestions for the worst-scoring requirements

## Notes

- The 31 metrics are deterministic — same input always produces same output
- NLP and entity extraction are enabled by default (off with `--basic`)
- Use `--per-req` for per-requirement breakdown
- Use `--json` for machine-readable output
- Use `--diagram text` for ASCII entity diagrams in terminal
