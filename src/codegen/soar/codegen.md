# codegen — SOAR-Powered Software Development Agent

This directory contains the SOAR production rule files for the `/codegen` pipeline.

## Spec 018 Feature Extensions

### Feature Summary Table

| Feature | Activation | Effect on Pipeline |
|---------|-----------|-------------------|
| F1: LSP Pre-Flight Gate | Automatic (always on) | Runs `mypy`/`tsc`/`go vet`/`mvn` before TEST phase; blocks on failure |
| F2: CQ-ISC Rule Packs | `active_packs: [pack_name]` in state | Loads composable rule packs into CQ-ISC library |
| F3: Auto-Constitution | `--extract-constitution [path] [--force]` | Scans codebase, generates `constitution.md` with Category S/B rules |
| F4: Anchoring Mode | `--anchor <path>` | Extracts style constraints from reference codebase; enforces for run duration |
| F5: Impasse Memory | Automatic (transparent) | Auto-applies prior human resolutions; escalates genuinely new conflicts |
| F6: Cross-Run SMEM | Automatic after DELIVER | Distills successful patterns into `codegen-patterns.yaml` for reuse |
| F7: Ψ Granularity | Automatic | Tracks Ψ per-criterion; detects DIVERGING; weighted formula |

---

### `--extract-constitution [<path>] [--force]`

Scans the target codebase and generates a `constitution.md` file containing auto-extracted coding rules.

**Arguments:**
- `<path>` — path to codebase to scan (default: current directory)
- `--force` — overwrite existing `constitution.md` (shows diff, requires confirmation)

**Example:**
```bash
codegen extract-constitution /path/to/project
codegen extract-constitution /path/to/project --force
```

**Output:**
- `constitution.md` in current directory with Category S (auto-enforceable) and Category B (advisory) rules
- Extraction confidence score per rule (`extraction_confidence: 0.82`)
- `EXTRACTION_DEGRADED` banner when fewer than 2 source types found
- `EXTRACTION_CONFIDENCE_LOW` banner when overall confidence < 0.70

**Sources analyzed:** TypeScript config (`tsconfig.json`), ESLint config, `.editorconfig`, test patterns, naming conventions

**Confidence formula:** `(source_coverage × 0.4) + (pattern_consistency × 0.4) + (rule_count_adequacy × 0.2)`
- ≥ 0.85 → Category S (auto-enforceable, admitted to SOAR SMEM)
- 0.70–0.85 → Category S with `requires_human_predicate: true`
- < 0.70 → Category B (advisory only)

---

### `--anchor <path>`

Activates Anchoring Mode for this pipeline run. Extracts style constraints from the reference codebase at `<path>` and enforces them during the IMPLEMENT phase.

**Arguments:**
- `<path>` — path to reference codebase to extract style from

**Example:**
```bash
codegen --anchor /path/to/reference-codebase run
```

**Dimensions analyzed:**
1. Naming conventions (camelCase / snake_case / PascalCase)
2. Import organization (stdlib → third-party → local)
3. Test structure patterns (pytest / unittest / jest)
4. Comment density (ratio of comment lines to total)
5. Abstraction level (function complexity via AST)

**Transient lifetime guarantee:** Anchoring constraints are cleared from working memory at DELIVER or ABORT. They do NOT persist to the next run. The next run without `--anchor` will have no anchoring WMEs present.

---

### F1: LSP Pre-Flight Gate

Automatically invoked before the TEST phase. Runs the project language's LSP/static analysis tool:

| Language | Tool | Timeout |
|----------|------|---------|
| Python | `mypy` | 30s |
| TypeScript / JavaScript | `tsc --noEmit` | 30s |
| Go | `go vet ./...` | 30s |
| Java | `mvn compile -q` | 30s |

**Outcomes:**
- `passed` → pipeline advances to TEST
- `failed` → pipeline blocked (Model B raises `PipelineBlockedError`)
- `unavailable` → tool not on PATH; pipeline continues with degraded quality (NFR-008)

---

### F7: Ψ Score Granularity

Ψ (Psi) now tracks per-criterion coverage across retry cycles.

**DIVERGING detection:** If a criterion is uncovered for ≥ `psi_diverging_threshold` (default: 2) consecutive cycles without improvement, it is marked DIVERGING and triggers human escalation via `ImpasseHandler`.

**Weighted formula:** `Ψ_weighted = Σ(weight × covered) / Σ(weight × eligible)`

Backward compatible: absent `weight` in state file → treated as 1.0.

**Pipeline summary table (per criterion):**
```
Criterion                      Covered  Trend  Status       Authority             Weight
------------------------------------------------------------------------------------------
CQ-ISC-SEC-001                 True     +1.00  ACTIVE       DEFAULT_LIBRARY         1.0
CQ-ISC-STYLE-001               False    +0.00  DIVERGING    DEFAULT_LIBRARY         2.0
```
