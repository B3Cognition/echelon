# EGR GitHub Reconciliation and Validity Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize all EGR register rows to GitHub, re-evaluate the seven unresolved findings against current source and focused tests, and publish the resulting authoritative statuses back to both surfaces.

**Architecture:** The existing register parser and idempotent GitHub sync script establish the initial and final parity boundaries. The audit is split by finding domain so each verdict has a small evidence set and focused verification command; only the register and its review metadata are edited locally.

**Tech Stack:** Python 3.11+, pytest, Git, GitHub CLI, Markdown register, existing `scripts/sync-egr-issues.py`.

## Global Constraints

- `docs/findings/echelon-grounded-review-register.md` remains authoritative.
- Perform the initial GitHub reconciliation before auditing unresolved findings.
- Code and focused passing tests are sufficient to classify an EGR as `fixed`.
- Do not change production code as part of this audit.
- Preserve dated historical finding documents and unrelated worktree changes.
- Use only `open`, `in-progress`, `fixed`, `superseded`, or `accepted-risk` statuses.
- A multi-part finding remains nonterminal while any material original contract remains unimplemented and non-obsolete.

---

### Task 1: Establish the synchronized GitHub baseline

**Files:**
- Read: `docs/findings/echelon-grounded-review-register.md`
- Execute: `scripts/sync-egr-issues.py`

**Interfaces:**
- Consumes: register rows parsed by `parse_register(Path) -> list[EgrFinding]`
- Produces: one GitHub issue per register EGR with matching title, body, priority label, status label, and open/closed state

- [ ] **Step 1: Confirm the execution boundary is clean and authenticated**

Run:

```bash
git status --short
gh auth status
git rev-parse HEAD
```

Expected: no uncommitted files; GitHub authentication succeeds; HEAD is recorded for the audit.

- [ ] **Step 2: Capture baseline register and GitHub counts**

Run:

```bash
awk -F'|' '/^\| EGR-/ {count++} END {print count}' docs/findings/echelon-grounded-review-register.md
gh issue list --repo B3Cognition/echelon --state all --limit 500 --json title --jq '[.[] | select(.title | test("^EGR-[0-9]{3}:"))] | length'
```

Expected: the register count is `162`; record the pre-sync GitHub count.

- [ ] **Step 3: Run the authoritative initial reconciliation**

Run:

```bash
python3 scripts/sync-egr-issues.py --repo B3Cognition/echelon
```

Expected: exit `0`; missing issues are created, existing issues updated, and terminal/nonterminal states reconciled.

- [ ] **Step 4: Verify exact baseline parity**

Run:

```bash
python3 - <<'PY'
import json
import importlib.util
import subprocess
import sys
from pathlib import Path

module_path = Path("scripts/sync-egr-issues.py")
spec = importlib.util.spec_from_file_location("sync_egr_issues", module_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)

register = module.parse_register(Path("docs/findings/echelon-grounded-review-register.md"))
raw = subprocess.check_output([
    "gh", "issue", "list", "--repo", "B3Cognition/echelon",
    "--state", "all", "--limit", "500",
    "--json", "number,title,state,labels,url",
], text=True)
issues = json.loads(raw)
by_id = {}
for issue in issues:
    title = issue["title"]
    if title.startswith("EGR-") and ":" in title:
        by_id.setdefault(title.split(":", 1)[0], []).append(issue)
errors = []
for finding in register:
    matches = by_id.get(finding.id, [])
    if len(matches) != 1:
        errors.append(f"{finding.id}: expected one issue, found {len(matches)}")
        continue
    issue = matches[0]
    labels = {label["name"] for label in issue["labels"]}
    expected_state = "CLOSED" if finding.status in module.CLOSE_REASON_BY_STATUS else "OPEN"
    if issue["state"] != expected_state:
        errors.append(f"{finding.id}: state {issue['state']} != {expected_state}")
    if set(finding.labels) - labels:
        errors.append(f"{finding.id}: missing labels {set(finding.labels) - labels}")
if errors:
    raise SystemExit("\n".join(errors))
print(f"PARITY_OK:{len(register)}")
PY
```

Expected: `PARITY_OK:162`.

### Task 2: Audit EGR-115 and EGR-119 deterministic verification ownership

**Files:**
- Read: `src/harness/ralph.py`
- Read: `src/harness/fulfillment_runner.py`
- Read: `src/harness/verify_spec_run.py`
- Read: `src/harness/judgment_prepass.py`
- Read: `src/harness/__main__.py`
- Read: `runtime/workflow/phases/verify-spec-*.md`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_fulfillment_runner.py`
- Test: `tests/unit/test_verify_spec_run_init.py`
- Test: `tests/unit/test_judgment_prepass.py`
- Test: `tests/unit/test_harness_main_fulfillment_artifacts.py`
- Test: `tests/unit/test_verify_spec_codegraph_prompt.py`
- Test: `tests/unit/test_verify_spec_reconcile_templates.py`

**Interfaces:**
- Consumes: EGR-115 and EGR-119 original finding and next-action contracts
- Produces: a verdict for each finding with exact source paths, test paths, remaining gaps, and confidence

- [ ] **Step 1: Trace which verify-spec operations are Python-owned and which still dispatch model judgment**

Run:

```bash
rg -n "verify-spec|fulfillment|judgment|fallback|assemble|reconcile|markerless" \
  src/harness/ralph.py src/harness/fulfillment_runner.py \
  src/harness/verify_spec_run.py src/harness/judgment_prepass.py \
  src/harness/__main__.py runtime/workflow/phases/verify-spec-*.md
```

Expected: enough call-site evidence to map deterministic preprocessing, bounded fallback judgment, final assembly, state stamping, and any remaining COMMANDER-owned deterministic decisions.

- [ ] **Step 2: Run the focused ownership and fulfillment test matrix**

Run:

```bash
pytest -q \
  tests/unit/test_fulfillment_runner.py \
  tests/unit/test_verify_spec_run_init.py \
  tests/unit/test_judgment_prepass.py \
  tests/unit/test_harness_main_fulfillment_artifacts.py \
  tests/unit/test_verify_spec_codegraph_prompt.py \
  tests/unit/test_verify_spec_reconcile_templates.py \
  tests/unit/test_ralph_outer.py
```

Expected: PASS. If a relevant test fails, neither finding may be marked `fixed`.

- [ ] **Step 3: Record separate EGR-115 and EGR-119 verdicts**

Classify each finding using the global rules. EGR-115 is fixed only if Ralph/Python owns the original deterministic recovery, provenance, task-progress, and refresh decisions. EGR-119 is fixed only if verify-spec orchestration is Python-owned end to end except explicitly bounded evidence-ID judgment.

### Task 3: Audit EGR-118 delivery containment

**Files:**
- Read: `src/harness/ralph.py`
- Read: `src/harness/llm_build_runner.py`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_llm_build_runner.py`

**Interfaces:**
- Consumes: generated `delivery-containment-policy.json` and `ECHELON_CONTAINMENT_POLICY_FILE`
- Produces: EGR-118 verdict covering absolute paths, workspace-relative paths, allowed context roots, sibling sources, transcript enforcement, and subagent delegation

- [ ] **Step 1: Inspect policy creation, propagation, and enforcement**

Run:

```bash
rg -n "delivery-containment-policy|allowed_context_roots|forbidden_source_roots|ECHELON_CONTAINMENT_POLICY_FILE|subagents" \
  src/harness/ralph.py src/harness/llm_build_runner.py \
  tests/unit/test_ralph_outer.py tests/unit/test_llm_build_runner.py
```

Expected: concrete policy generation and runner-side transcript enforcement are visible with focused coverage.

- [ ] **Step 2: Run containment tests**

Run:

```bash
pytest -q tests/unit/test_llm_build_runner.py tests/unit/test_ralph_outer.py
```

Expected: PASS.

- [ ] **Step 3: Record the EGR-118 verdict**

Mark `fixed` only if the code deterministically denies forbidden sibling-source access while preserving explicitly allowed context roots, including delegated/subagent access paths covered by tests.

### Task 4: Audit EGR-142 estimate consistency and provenance

**Files:**
- Read: `src/`
- Read: `runtime/templates/estimates-template.md`
- Read: `runtime/workflow/phases/phase2-decide.md`
- Read: `runtime/workflow/phases/phase3-consensus.md`
- Test: `tests/`

**Interfaces:**
- Consumes: published `estimates.md` artifacts and any estimate provenance model
- Produces: EGR-142 verdict covering summary/detail consistency, material-change provenance, and publication enforcement

- [ ] **Step 1: Search for executable estimate validation and provenance**

Run:

```bash
rg -n "estimates\.provenance|estimate.*provenance|validate.*estimate|estimate.*consisten|person-weeks|unadjusted.*FP|adjusted.*FP" src runtime tests
```

Expected: either concrete parser/validator/provenance implementation and tests, or evidence that the original gap remains.

- [ ] **Step 2: Run any directly relevant estimate tests discovered in Step 1**

Run each discovered focused test module with `pytest -q <path>`. If no implementation-specific tests exist, record that absence and do not mark the finding `fixed`.

- [ ] **Step 3: Record the EGR-142 verdict**

Require all material original contracts for `fixed`: deterministic consistency validation, material-change provenance, and publication blocking/debt marking.

### Task 5: Audit EGR-144 and EGR-146 checkpoint and rerun operations

**Files:**
- Read: `src/harness/phase_checkpoints.py`
- Read: `src/echelon/checkpoint_cli.py`
- Read: `src/echelon/cli.py`
- Read: `runtime/workflow/definition.yaml`
- Test: `tests/unit/test_phase_checkpoints.py`
- Test: `tests/unit/test_cli_checkpoint.py`
- Test: `tests/unit/test_squad_phase_checkpoints.py`
- Test: `tests/unit/test_squad_checkpoint_context.py`

**Interfaces:**
- Consumes: workflow phase graph, checkpoint ledger, CLI command routing
- Produces: separate verdicts for checkpoint-coverage policy and supported phase rerun semantics

- [ ] **Step 1: Inspect checkpoint selection and CLI command surfaces**

Run:

```bash
rg -n "checkpoint|rewind|rerun|coverage" \
  src/harness/phase_checkpoints.py src/echelon/checkpoint_cli.py src/echelon/cli.py \
  runtime/workflow/definition.yaml tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_checkpoint.py tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_squad_checkpoint_context.py
```

Expected: exact evidence for which phases checkpoint, how coverage is surfaced, and whether `echelon spec rerun` exists with deterministic downstream invalidation.

- [ ] **Step 2: Run checkpoint-focused tests**

Run:

```bash
pytest -q \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_squad_checkpoint_context.py
```

Expected: PASS.

- [ ] **Step 3: Record separate EGR-144 and EGR-146 verdicts**

EGR-144 is fixed only if a deterministic coverage policy is implemented, tested, and operator-visible. EGR-146 is fixed only if supported rerun semantics exist and are tested; improved rewind behavior alone is insufficient.

### Task 6: Audit EGR-149 shared lifecycle control

**Files:**
- Read: `src/echelon/spec_lifecycle.py`
- Read: `src/harness/re_lifecycle.py`
- Read: delivery lifecycle/control paths under `src/harness/`
- Test: `tests/unit/test_spec_lifecycle.py`
- Test: `tests/unit/test_re_lifecycle.py`
- Test: applicable delivery lifecycle tests discovered by search

**Interfaces:**
- Consumes: spec, RE, and delivery run/continue/resume state-transition implementations
- Produces: EGR-149 verdict distinguishing a proven shared abstraction from three still-separate lifecycle implementations

- [ ] **Step 1: Compare lifecycle primitives and adapters**

Run:

```bash
rg -n "current_run|continue|resume|reset|blocker|terminal|lifecycle|classif|escalat" \
  src/echelon/spec_lifecycle.py src/harness/re_lifecycle.py src/harness \
  tests/unit/test_spec_lifecycle.py tests/unit/test_re_lifecycle.py
```

Expected: evidence of either an extracted shared control-plane interface with conformance coverage or remaining lifecycle-specific implementations.

- [ ] **Step 2: Run relevant lifecycle tests**

Run:

```bash
pytest -q tests/unit/test_spec_lifecycle.py tests/unit/test_re_lifecycle.py tests/unit/test_cli_re_lifecycle.py
```

Expected: PASS; passing independent lifecycle tests do not by themselves prove the shared-abstraction contract.

- [ ] **Step 3: Record the EGR-149 verdict**

Mark `fixed` only if proven-invariant mechanics are behind a shared abstraction and a cross-lifecycle conformance suite exists. Mark `superseded` only if a newer explicit architecture decision rejects that objective.

### Task 7: Update the register from evidence

**Files:**
- Modify: `docs/findings/echelon-grounded-review-register.md`

**Interfaces:**
- Consumes: seven audit verdicts with source and test evidence
- Produces: authoritative statuses, evidence, next actions, `Last updated`, and `Last delta review HEAD`

- [ ] **Step 1: Edit only the audited rows and review metadata**

Use `apply_patch` to update EGR-115, EGR-118, EGR-119, EGR-142, EGR-144, EGR-146, and EGR-149. Set `Last updated` to `2026-08-11` and `Last delta review HEAD` to the commit audited before register edits.

- [ ] **Step 2: Validate register syntax and status vocabulary**

Run:

```bash
python3 - <<'PY'
import importlib.util
import sys
from pathlib import Path

allowed = {"open", "in-progress", "fixed", "superseded", "accepted-risk"}
module_path = Path("scripts/sync-egr-issues.py")
spec = importlib.util.spec_from_file_location("sync_egr_issues", module_path)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)
rows = module.parse_register(Path("docs/findings/echelon-grounded-review-register.md"))
assert len(rows) == 162, len(rows)
bad = [(row.id, row.status) for row in rows if row.status not in allowed]
assert not bad, bad
assert len({row.id for row in rows}) == len(rows)
print("REGISTER_OK:162")
PY
git diff --check
```

Expected: `REGISTER_OK:162`; `git diff --check` emits no output.

- [ ] **Step 3: Review the exact register delta**

Run:

```bash
git diff -- docs/findings/echelon-grounded-review-register.md
```

Expected: only metadata and the seven audited rows changed.

### Task 8: Publish final GitHub state and verify completion

**Files:**
- Read: `docs/findings/echelon-grounded-review-register.md`
- Execute: `scripts/sync-egr-issues.py`
- Commit: updated register

**Interfaces:**
- Consumes: final authoritative register
- Produces: final GitHub parity, committed audit result, and unresolved-EGR summary

- [ ] **Step 1: Run the final GitHub synchronization**

Run:

```bash
python3 scripts/sync-egr-issues.py --repo B3Cognition/echelon
```

Expected: exit `0`; issue states and managed labels reflect the audited register.

- [ ] **Step 2: Repeat exact parity verification**

Repeat Task 1 Step 4.

Expected: `PARITY_OK:162`.

- [ ] **Step 3: Run final local verification**

Run:

```bash
git diff --check
git status --short
awk -F'|' '/^\| EGR-/ {id=$2; p=$3; s=$4; gsub(/^ +| +$/, "", id); gsub(/^ +| +$/, "", p); gsub(/^ +| +$/, "", s); if (s == "open" || s == "in-progress") print id "\t" p "\t" s}' docs/findings/echelon-grounded-review-register.md
```

Expected: no whitespace errors; only the intended register modification is uncommitted; output is the final unresolved-EGR list.

- [ ] **Step 4: Commit the authoritative audit result**

Run:

```bash
git add docs/findings/echelon-grounded-review-register.md
git commit -m "docs: reconcile EGR validity audit"
```

Expected: commit succeeds with only the register change.
