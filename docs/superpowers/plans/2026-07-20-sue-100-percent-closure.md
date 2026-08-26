# SUE 100% Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining ~20% of the SUE pipeline against the original research design (SRP v0 spec + v3 design addenda + reasoning-layer verdict) so that every designed element is either built-and-measured or closed-as-falsified with evidence.

**Architecture:** Five standalone stdlib-only scripts (`scripts/sue_*.py`) remain the substrate. The closure work is (a) two code upgrades to `sue_reproducibility.py` — glossary-canonical alignment and exhibited-witness verification, (b) four live measurement campaigns — A1 gate, witness A/B, H4 cross-family, H-D2 build-pilot, (c) the full SRP corpus run producing the A1–A6 scorecard and decision memo, and (d) workflow integration gated on a corpus PASS.

**Tech Stack:** Python 3 stdlib only (FR-045 forbids importing the lexicon package into SUE scripts), `claude -p` / `codex exec` subprocess providers, pytest with the replay-stub seam in `tests/unit/test_sue_*.py`.

## Global Constraints

- SUE scripts are stdlib-only; **no echelon/lexicon imports** (FR-045). Glossary reading must be a deterministic line scan of `<spec-dir>/glossary.md`.
- Reports are written **beside the spec**; the challenged spec is never modified; report-path collision guard stays.
- Exit codes: 0 success · 1 bad input · 2 model command not found · 3 unusable output after retry.
- SR comparisons are valid only between runs of the **same tool version and unit families** (docs/sue-usage.md §3).
- Labels obey the v3.1 vocabulary anchor: every word of an edge label appears verbatim in the cited line (`_label_grounded`). Glossary canonicalization therefore acts at **alignment time**, never by relaxing the anchor.
- Per-requirement scores are trustworthy only via `--passes ≥2` intersection (`aggregate_passes.stable_low`).
- Live-run budget discipline: every live task states its call count before running; stop any campaign that exceeds 2× its estimate (the 2026-07-18/19 sessions burned ~$180 routing around harness bugs — see memory `echelon-upstream-bugs-2026-07`).
- **Coordination note (2026-07-20, resolved 12:27):** the background agent landed its work as b3bd23dd (`--passes` multi-pass stability, 5 tests), 1e8f17b9 (J-graph convergence layer, 4 tests), d9eec57e (usage-guide/pre-registration docs). 76/76 SUE unit tests pass on the landed state. Code blocks below anchor to **function names, not line numbers**.

## Traceability — research design element → closing task

| Research-design element | Status today | Closing task |
|---|---|---|
| ≥2-run intersection for per-requirement scores | **landed** (b3bd23dd: `--passes`, `aggregate_passes`, `stable_low`; tests pass) | Task 0 (done: steps 1–2) |
| Extraction-noise floor measured, not estimated (~0.35) | **measured** (2026-07-20, spec 030, Fable 5 readers, `--passes 2`): per-req cross-pass floor **0.143** (confirms the earlier ±0.14 A/B estimate; the old ~0.35 figure was a different metric — pairwise-agreement shortfall), SR 0.453±0.008, stable_low = 34/83 units | Task 0 (done) |
| Glossary-resolved labels (probe §5 stabilization, alignment step 3) | missing | Task 1 |
| A1 gate: clean-spec agreement ≥ 0.80 mean / ≥ 0.70 min → SR absolute | not met (0.35 floor) | Task 2 |
| Witness channel A/B re-validation after canonical situations (d629290a) | pending | Task 3 |
| Cross-pass witness intersection (stable candidates) | missing (witnesses use last pass only) | Task 3 |
| Reasoning Graph: one-shot J-graph H-D2 build-pilot (modified outcome 2) | **convergence layer landed** (1e8f17b9: consensus conflicts, convergence rate, evidence completeness; offline-validated on real 064 graphs — FR-001×AC-5 unanimous 3/3). The Codex-audit blinded-adjudication protocol (matched budgets, human primary, direct auditability scoring) remains un-run | Task 4 (now the rigor tier on top of the landed metrics) |
| Exhibited behavioural witnesses (Grounded Divergence Witness standard, v4 debt 2) | candidates only | Task 5 |
| Heterogeneous model families live (H4 prerequisite, v4 debt 5a) | code ready, flags unverified live | Task 6 |
| Critical-fact retention (v4 debt 5b) | `⚠ RETENTION` flag in dialectic only | Task 7 (scope + surface) |
| SRP corpus run: M1–M5 mutants, measurements 1–8, A1–A6 scorecard, decision memo | not run | Task 8 |
| Workflow integration: WHY3 feed, state keys, journal types | recorded, not built | Task 9 (gated on Task 8 PASS) |
| Documentation honesty: usage-guide caveats reflect measured state | caveats reflect estimates | Task 10 |

A task that *falsifies* its element (e.g. A1 unreachable, H-D2 demotes to outcome 3) still **closes** it: the deliverable is the recorded result and the updated caveat, per the project's standing practice of reporting its own falsifications.

---

### Task 0: Land and verify the in-flight `--passes` work (gate for all other tasks)

**Files:**
- Verify only (owned by the background agent until committed): `scripts/sue_reproducibility.py`, `scripts/sue_jgraph.py`, `tests/unit/test_sue_reproducibility.py`

**Interfaces:**
- Produces: committed `--passes N` flag; `aggregate_passes(pass_scores, threshold=0.5) -> dict` with keys `passes, sr_mean, sr_stdev, sr_series, extraction_noise_floor, per_requirement{mean,stdev,min,max,passes,stable_low,noise_bounded_low}, stable_low`; `stability` compartment in report + sidecar. All later tasks consume this.

- [x] **Step 1: Wait for the background agent to finish and commit.** Done 2026-07-20 12:27 — landed as b3bd23dd / 1e8f17b9 / d9eec57e.
- [x] **Step 2: Run the unit suite.** Done 2026-07-20: 76 passed (includes `TestAggregatePasses`, jgraph convergence tests).

Run: `pytest tests/unit/test_sue_reproducibility.py -q`
Expected: all tests pass, including new `aggregate_passes` / `--passes` tests. If the agent left no tests for `aggregate_passes`, write them now (cases: 2 passes identical scores → stdev 0, stable_low only below threshold in both; requirement present in only one pass excluded from `per_requirement`; `extraction_noise_floor` = mean of per-req stdevs; single-pass input → `sr_stdev` 0).

- [x] **Step 3: Live 2-pass measurement to replace the ~0.35 noise-floor estimate with a measured number.** Done 2026-07-20 (Fable 5 readers): extraction_noise_floor **0.143**, SR 0.453±0.008 (series 0.4448/0.4609), stable_low 34/83. Artifacts preserved in session scratchpad as `sr-030-fable5-2pass.{md,json}`.

Run (~30 calls: 3 readers × ~5 chunks × 2 passes):
```bash
python3 scripts/sue_reproducibility.py specs/030-build-sue-challenge-script/spec.md --passes 2
```
(The sidecar `semantic-reproducibility.json` lands beside the spec — no redirect needed.)
Expected: report shows a "Cross-pass stability" section; record `extraction_noise_floor`, `sr_stdev`, and the `stable_low` set. This number is the Task 2 baseline.

- [ ] **Step 4: Commit anything you had to add (tests), update memory.** Update `sue-challenge-script.md` memory: `--passes` landed, measured noise floor value.

### Task 1: Glossary-canonical alignment (absolute-SR fix, code half)

The probe's extraction-stabilization prescription (§5) and alignment step 3 (lexicon aliases/synonyms): labels that normalize to a declared glossary term are aligned **to that term** before Jaccard, deterministically. This removes the choice-of-span component of vocabulary divergence without touching the v3.1 grounding anchor.

**Files:**
- Modify: `scripts/sue_reproducibility.py` (add two functions after `norm()`; touch `score_requirements`, `build_extraction_prompt`, `render_report`, `build_sidecar`, `main`)
- Test: `tests/unit/test_sue_reproducibility.py`

**Interfaces:**
- Produces: `parse_glossary_terms(spec_dir: Path) -> dict[str, str]` (normalized form → canonical term), `canonicalize(label: str, glossary: dict) -> str`; `score_requirements(readers, glossary=None)` gains an optional param; sidecar gains `"glossary": {"present": bool, "terms": int, "canonicalized_labels": int}`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_parse_glossary_terms_reads_headings(tmp_path):
    (tmp_path / "glossary.md").write_text(
        "# Domain Glossary\n\n## Terms\n\n### Spec Run\n- **Definition:** x\n"
        "### state.json\n- **Definition:** y\n### Builder\n- text\n",
        encoding="utf-8")
    terms = v3.parse_glossary_terms(tmp_path)
    assert terms == {
        "spec run": "spec run", "state.json": "state.json", "builder": "builder"}

def test_parse_glossary_terms_missing_file(tmp_path):
    assert v3.parse_glossary_terms(tmp_path) == {}

def test_canonicalize_maps_span_variants_to_term():
    glossary = {"spec run": "spec run"}
    # singular/article/word-subset variants of a declared term collapse to it
    assert v3.canonicalize("the spec runs", glossary) == "spec run"
    assert v3.canonicalize("spec run", glossary) == "spec run"
    # labels that are NOT a declared term pass through normalized only
    assert v3.canonicalize("run list", glossary) == v3.norm("run list")

def test_canonicalize_never_merges_distinct_terms():
    glossary = {"spec run": "spec run", "run list": "run list"}
    # a label containing words of two terms must not force-merge (probe: never force-merge)
    assert v3.canonicalize("spec run list", glossary) == v3.norm("spec run list")

def test_scoring_with_glossary_aligns_span_variants():
    glossary = {"spec run": "spec run"}
    r1 = _reader(1, {"REQ-001": _interp(
        edges=[_edge("builder", "the spec runs", "acts_on", 5)])})
    r2 = _reader(2, {"REQ-001": _interp(
        edges=[_edge("builder", "spec run", "acts_on", 5)])})
    scored = v3.score_requirements([r1, r2], glossary=glossary)
    assert scored["REQ-001"]["score"] == 1.0
```

(Uses the existing module-level test helpers exactly as defined: `_reader(no, reqs)` takes a `{req_id: _interp(...)}` dict, `_edge(s, t, etype, line)`, and the module under test is imported as `v3` via `_load`.)

- [ ] **Step 2: Run tests to verify they fail.**

Run: `pytest tests/unit/test_sue_reproducibility.py -k glossary -v`
Expected: FAIL with `AttributeError: ... no attribute 'parse_glossary_terms'`

- [ ] **Step 3: Implement.** Insert after `norm()` in `scripts/sue_reproducibility.py`:

```python
_GLOSSARY_HEADING_RE = re.compile(r"^###\s+(.+?)(?:\s+\(.*\))?\s*$")


def parse_glossary_terms(spec_dir: Path) -> dict:
    """Declared vocabulary from <spec-dir>/glossary.md (### Term headings).

    Deterministic line scan — FR-045 forbids importing the lexicon package.
    Returns {normalized term: normalized term}; the identity mapping is the
    alignment target (aliases collapse via norm()). Missing file -> {}.
    """
    path = spec_dir / "glossary.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    terms: dict = {}
    for line in lines:
        head = _GLOSSARY_HEADING_RE.match(line.strip())
        if head:
            canonical = norm(head.group(1))
            if canonical:
                terms[canonical] = canonical
    return terms


def canonicalize(label: str, glossary: dict) -> str:
    """Alignment step 3 (probe §6): map a label onto a declared glossary term.

    A label aligns to a term iff its normalized word-set equals the term's —
    i.e. only article/plural/whitespace span variants collapse. Word-subset or
    -superset labels do NOT align (never force-merge). Non-matches return the
    plain normalized label, so scoring without a glossary is unchanged.
    """
    normalized = norm(label)
    if normalized in glossary:
        return glossary[normalized]
    label_words = frozenset(normalized.split(" "))
    matches = [term for term in glossary
               if frozenset(term.split(" ")) == label_words]
    return matches[0] if len(matches) == 1 else normalized
```

Thread it through (anchored by function name, exact edits to be rebased on the landed `--passes` state):

- `score_requirements(readers, glossary=None)`: where edge triples are collected (`{e.triple for e in ...}`), map each triple through the glossary when one is present:
  ```python
  def _canon_triples(interp):
      triples = {e.triple for e in interp.edges}
      if not glossary:
          return triples
      return {(canonicalize(s, glossary), t, canonicalize(o, glossary))
              for s, t, o in triples}
  ```
  and use `_canon_triples(...)` for both sides of every pair. Count `canonicalized_labels` (labels where `canonicalize(...) != norm(...)`) into the returned per-req dicts' new key `glossary_hits`.
- `build_extraction_prompt`: when the caller passes a non-empty glossary, append one rule line: `"DECLARED VOCABULARY (prefer these exact terms as labels when the cited line contains their words): " + ", ".join(sorted(glossary))` — capped at 60 terms (`sorted(glossary)[:60]`) to bound prompt growth.
- `main`: `glossary = parse_glossary_terms(spec_dir)`; pass to `build_extraction_prompt` and `score_requirements`; add `--no-glossary` flag (`action="store_true"`) to disable for A/B comparison.
- `build_sidecar` / `render_report`: emit `"glossary": {"present": bool(glossary), "terms": len(glossary), "canonicalized_labels": total_hits}` and one report line under Diagnostics.

- [ ] **Step 4: Run the full suite.**

Run: `pytest tests/unit/test_sue_reproducibility.py -q`
Expected: PASS (new + all existing tests — existing tests exercise the `glossary=None` path unchanged).

- [ ] **Step 5: Commit.**

```bash
git add scripts/sue_reproducibility.py tests/unit/test_sue_reproducibility.py
git commit -m "feat: v3 glossary-canonical alignment — probe step-3 alias resolution"
```

### Task 2: A1 gate re-measurement (absolute-SR fix, measurement half)

**Files:**
- Create: `docs/superpowers/reports/2026-07-XX-sue-a1-gate.md` (result memo, either outcome)
- Modify on PASS: `docs/sue-usage.md` §3 caveat, `docs/superpowers/specs/2026-07-19-sue-v3-reproducibility-design.md` (addendum)

**Interfaces:**
- Consumes: Task 0's measured noise floor (baseline), Task 1's `--no-glossary` flag (control arm).

- [ ] **Step 1: Paired measurement on two clean specs (~120 calls total; ~4 runs × ~15 calls × 2 specs).** For each of `specs/029-builder-spec-workbench/spec.md` and `specs/030-build-sue-challenge-script/spec.md`:

```bash
python3 scripts/sue_reproducibility.py <spec> --passes 2 --json > with-glossary.json
python3 scripts/sue_reproducibility.py <spec> --passes 2 --no-glossary --json > without.json
```

- [ ] **Step 2: Score against the pre-registered thresholds.** From each sidecar's `stability` block record `sr_mean`, `extraction_noise_floor`, per-req `min`. A1 (probe §9): mean pairwise agreement **≥ 0.80**, min per spec **≥ 0.70**, on the glossary arm.
- [ ] **Step 3: Write the result memo** with the four sidecar summaries, the glossary-vs-control delta, and the verdict:
  - **A1 met** → SR is promoted from comparative to absolute for glossary-bearing specs. Update `docs/sue-usage.md` §3: replace "SR score is comparative, not absolute" with the measured statement and its scope condition (glossary present, `--passes ≥2`). Add a dated addendum to the v3 design doc.
  - **A1 not met** → per the probe: *iterate on extraction, not on the corpus*. Record the measured floor, keep the caveat verbatim, and list the next candidate lever (edge-segmentation exemplars) in the memo. Task 8 stays gated.
- [ ] **Step 4: Commit** memo + any doc updates: `git add docs/ && git commit -m "docs: A1 gate measurement — <verdict>"`.

### Task 3: Witness channel — live A/B re-validation + cross-pass stable candidates

**Files:**
- Modify: `scripts/sue_reproducibility.py` (`find_witnesses` per pass + intersection; check first — the background agent may have built this), `tests/unit/test_sue_reproducibility.py`
- Create: result section appended to the Task 2 memo

**Interfaces:**
- Consumes: `aggregate_passes` shape from Task 0; `Witness` dataclass (`req_id, given, when, sides, kind`).
- Produces: sidecar `stability.stable_witnesses` — list of `(req_id, normalized (given, when))` keys present in **every** pass.

- [x] **Step 1: Check whether the landed `--passes` work already intersects witnesses.** Checked 2026-07-20: it does not — witnesses/fractures/evidence use the last pass only (comment above the `stability` aggregation in `main`). Steps 2–3 are required.
- [ ] **Step 2: Write the failing test.**

```python
def test_stable_witnesses_intersect_across_passes():
    def _w(req, giv, whn):
        mk = lambda then: v3.Assertion(given=giv, when=whn, then=then, lines=[3])
        return v3.Witness(req_id=req, given=giv, when=whn,
                          sides=[(1, mk("a")), (2, mk("b"))])
    passes = [[_w("REQ-001", "g1", "w1"), _w("REQ-002", "g2", "w2")],
              [_w("REQ-001", "g1", "w1")]]
    stable = v3.stable_witness_keys(passes)
    assert stable == [("REQ-001", v3.norm("g1"), v3.norm("w1"))]
```

- [ ] **Step 3: Implement** `stable_witness_keys(witnesses_per_pass: list) -> list` (set-intersection over `(req_id, norm(given), norm(when))` keys); in `main`, collect `find_witnesses(readers)` per pass, store the intersection in the `stability` dict as `stable_witnesses`, and mark stable candidates `**stable**` in the report's candidate section. Run `pytest tests/unit/test_sue_reproducibility.py -q` → PASS. Commit: `git commit -m "feat: v3 cross-pass stable witness candidates"`.
- [ ] **Step 4: Live A/B on the lexicon spec (canonical-situations channel, d629290a).** `--passes 2` on `specs/029-builder-spec-workbench/spec.md` (already run in Task 2 — reuse that sidecar). Verdict criteria: witness-candidate counts per pass within ±30% of each other (no 27-vs-0 lottery), and `stable_witnesses` non-degenerate (neither empty while per-pass counts are high, nor equal to the union). Record the counts in the memo; update the memory file's "live A/B re-validation of the witness channel still pending" clause.

### Task 4: H-D2 build-pilot — the Reasoning Graph decision (closes the missing layer)

Modified outcome 2 (pre-registration RESULT, f7584c85): `sue_jgraph.py` is the only automated Reasoning Graph candidate, as an **instrumented pilot**. H-D2: D-graphs must reach **≥80% of arm-C trace completeness**, be **blindly auditable**, and support **graph-only contradiction detection** — else demote to outcome 3 (no automated reasoning layer; dialectic stays manual-Forensic).

**Landed 2026-07-20 (1e8f17b9):** the convergence layer now exists in `sue_jgraph.py` — evidence-line-anchored conflict alignment across readers, consensus conflicts (≥2 readers), conflict-convergence rate, unanimous count, mean evidence completeness — offline-validated on the real 064 graphs (FR-001×AC-5 unanimous 3/3, 40% convergence, 100% completeness). What this task still owes is the **blinded protocol** from the Codex audit: those numbers were computed unblinded on the two specs the pilot was designed around. Steps below are the rigor tier; they can *demote* the promotion but no longer need to build instrumentation.

**Files:**
- Create: `docs/superpowers/experiments/2026-07-XX-hd2-pilot/` — `protocol.md` (pre-registered BEFORE runs), `packaging/` (blinded items), `judges/*.json`, `RESULT.md`
- Verify/modify: `scripts/sue_jgraph.py` provenance output (background agent is editing it now — reconcile first)

**Interfaces:**
- Consumes: committed arm-C traces (`docs/superpowers/experiments/2026-07-19-reasoning-layer/`), the 5 pre-registered seeds, `sue_jgraph.py` (claims with evidence lines, `⚡ conflicts` pairs).

- [ ] **Step 1: Pre-register `protocol.md`** implementing all six Codex-audit follow-ups, each as a numbered protocol clause:
  1. one blinded packaging template holding full-chain C traces AND D graphs with equivalent provenance fields (claim, evidence lines, derivation path);
  2. matched budgets on **both calls and tokens** (record per item);
  3. semantic dedup of pooled items before any yield analysis (dedup key: normalized claim text + target unit);
  4. judges pre-registered: ≥1 cross-family (codex) + human primary (the operator scores before seeing any model verdict);
  5. direct per-item scoring of: precision, evidence-link completeness, blind auditability (can the judge reconstruct why the claim holds from the package alone), graph-only contradiction detection (is each known contradiction recoverable from the D graph without the C chain);
  6. the pre-registered decision rule: PASS = D ≥ 80% of C-trace completeness AND every tier-2 known contradiction (029 REQ-002/023+029/010 seeds; 064 FR-025b, FR-001×AC-5) recoverable graph-only; else outcome 3.
- [ ] **Step 2: Generate arm-D packages** (~6 calls: 3 readers × 2 specs, reusing the landed `sue_jgraph.py`):

```bash
python3 scripts/sue_jgraph.py specs/029-builder-spec-workbench/spec.md --readers 3
python3 scripts/sue_jgraph.py \
  /Users/ladislavbihari/myWork/infra/ru-sixth-sense/specs/064-eventlog-inline-edit/spec.md --readers 3
```

- [ ] **Step 3: Package blindly, adjudicate, score.** Fill the template for every deduplicated item; hold the arm-label key out of the packages (as `adjudication-KEY.txt` was); human scores first, then codex + one same-family judge; compute the five direct scores per arm.
- [ ] **Step 4: Write `RESULT.md`** with the verdict:
  - **PASS** → J-graph is the reasoning layer: record promotion, wire `sue_jgraph` output into the v3 sidecar's `proto_justification` compartment as a follow-on task (schema seam already exists — v3.3 addendum item 3), and update `docs/sue-usage.md` §5 status line.
  - **FAIL** → outcome 3: the reasoning layer is closed as "manual Forensic only"; update usage guide §5 and the memory file. Either verdict closes the layer against the research report.
- [ ] **Step 5: Commit** experiment directory + doc updates.

### Task 5: Exhibited behavioural witnesses (v4 debt 2 — Grounded Divergence Witness standard)

Upgrade stable witness candidates from "normalized-string difference" to **exhibited incompatibility**: one verification call per stable candidate must produce a concrete situation where the two `then` clauses mandate incompatible outcomes, citing both sides' lines — or classify the pair as equivalent/undetermined.

**Files:**
- Modify: `scripts/sue_reproducibility.py`, `tests/unit/test_sue_reproducibility.py`

**Interfaces:**
- Consumes: `stable_witness_keys` (Task 3), `v1.execute_round` retry seam, `Witness` dataclass.
- Produces: `--verify-witnesses` flag (off by default); `verify_witness_prompt(spec, witness) -> str`; `validate_witness_verdict(payload, witness, max_line)` → `dict | v1.ParseFailure`; report section "Verified witnesses" distinct from candidates; sidecar `witness['verdict']` ∈ `incompatible | equivalent | undetermined`.

- [ ] **Step 1: Write the failing tests.**

```python
def _witness_with_lines(a_lines, b_lines):
    a = v3.Assertion(given="g", when="w", then="the file persists",
                     lines=list(a_lines))
    b = v3.Assertion(given="g", when="w", then="the save is blocked",
                     lines=list(b_lines))
    return v3.Witness(req_id="REQ-001", given="g", when="w",
                      sides=[(1, a), (2, b)])


def test_validate_witness_verdict_requires_both_citations():
    w = _witness_with_lines(a_lines=[7], b_lines=[12])
    ok = v3.validate_witness_verdict(
        {"verdict": "incompatible", "situation": "s",
         "outcome_a": "x", "outcome_b": "y", "lines": [7, 12]}, w, max_line=50)
    assert ok["verdict"] == "incompatible"
    missing = v3.validate_witness_verdict(
        {"verdict": "incompatible", "situation": "s",
         "outcome_a": "x", "outcome_b": "y", "lines": [7]}, w, max_line=50)
    assert isinstance(missing, v3.v1.ParseFailure)

def test_validate_witness_verdict_rejects_unknown_verdict():
    w = _witness_with_lines(a_lines=[7], b_lines=[12])
    bad = v3.validate_witness_verdict(
        {"verdict": "conflict", "situation": "s",
         "outcome_a": "x", "outcome_b": "y", "lines": [7, 12]}, w, max_line=50)
    assert isinstance(bad, v3.v1.ParseFailure)

def test_equivalent_verdict_needs_no_lines():
    w = _witness_with_lines(a_lines=[7], b_lines=[12])
    ok = v3.validate_witness_verdict(
        {"verdict": "equivalent", "reason": "same outcome reworded"},
        w, max_line=50)
    assert ok["verdict"] == "equivalent"
```

- [ ] **Step 2: Run to verify failure.** `pytest tests/unit/test_sue_reproducibility.py -k witness_verdict -v` → FAIL (`validate_witness_verdict` undefined).
- [ ] **Step 3: Implement.**

```python
WITNESS_VERDICTS = ("incompatible", "equivalent", "undetermined")


def verify_witness_prompt(spec, witness) -> str:
    (ra, a), (rb, b) = witness.sides[0], witness.sides[1]
    return (
        "Two isolated readers of the same specification produced assertions "
        "with the same given/when but different then-clauses. Decide whether "
        "the two then-clauses are behaviourally INCOMPATIBLE (no system could "
        "satisfy both), EQUIVALENT (same outcome, different words), or "
        "UNDETERMINED by the specification text.\n\n"
        f"GIVEN: {a.given}\nWHEN: {a.when}\n"
        f"THEN (reader A, lines {sorted(a.lines)}): {a.then}\n"
        f"THEN (reader B, lines {sorted(b.lines)}): {b.then}\n\n"
        "SPECIFICATION (line-numbered):\n"
        f"{v1.numbered_text(spec)}\n\n"
        "If incompatible: exhibit ONE concrete situation and the two mandated "
        "outcomes, citing the specification lines BOTH readers relied on. "
        "Return ONLY JSON: {\"verdict\": \"incompatible|equivalent|"
        "undetermined\", \"situation\": str, \"outcome_a\": str, "
        "\"outcome_b\": str, \"lines\": [int], \"reason\": str} — "
        "situation/outcomes/lines required only for incompatible."
    )


def validate_witness_verdict(payload: dict, witness, max_line: int):
    verdict = payload.get("verdict")
    if verdict not in WITNESS_VERDICTS:
        return v1.ParseFailure(
            reason=f"verdict must be one of {', '.join(WITNESS_VERDICTS)}")
    if verdict != "incompatible":
        return {"verdict": verdict, "reason": str(payload.get("reason", ""))}
    lines = payload.get("lines")
    if (not isinstance(lines, list) or not lines
            or not all(isinstance(n, int) and 1 <= n <= max_line for n in lines)):
        return v1.ParseFailure(reason="incompatible verdict needs valid lines")
    cited = set(lines)
    for _, assertion in witness.sides[:2]:
        if not cited & set(assertion.lines):
            return v1.ParseFailure(
                reason="incompatible verdict must cite lines from BOTH sides")
    if not all(str(payload.get(k, "")).strip()
               for k in ("situation", "outcome_a", "outcome_b")):
        return v1.ParseFailure(
            reason="incompatible verdict needs situation and both outcomes")
    return {"verdict": "incompatible",
            "situation": str(payload["situation"]),
            "outcome_a": str(payload["outcome_a"]),
            "outcome_b": str(payload["outcome_b"]),
            "lines": sorted(cited)}
```

In `main` (after witnesses are computed, only when `options.verify_witnesses` and the candidate is in `stable_witnesses`): one `v1.execute_round(...)` per stable candidate with the prompt/validator above (round numbering: continue the existing scheme with a distinct band, e.g. `900000 + index`); attach the verdict dict to the witness; render an "Exhibited witnesses (verified)" report section listing only `incompatible` verdicts with their situation/outcomes/lines, and keep everything else under candidates. Sidecar: `witness["verdict"]`. Help text must state the cost: "+1 call per stable candidate".

- [ ] **Step 4: Run the full suite.** `pytest tests/unit/test_sue_reproducibility.py -q` → PASS.
- [ ] **Step 5: Live smoke (bounded: only stable candidates, typically ≤8 calls).** Re-run 029 with `--passes 2 --verify-witnesses`; confirm verified witnesses render and candidates remain labelled heuristic.
- [ ] **Step 6: Commit.** `git commit -m "feat: v4 exhibited behavioural witnesses — verified incompatibility on stable candidates"`

### Task 6: Live H4 cross-family run

**Files:**
- Create: result section in the Task 2/3 memo (same file)

- [ ] **Step 1: Verify the codex CLI live** (usage guide: "flags pending first live verification"): `echo "say OK" | codex exec --ephemeral --skip-git-repo-check --sandbox read-only -` — fix the adapter flags in `v1.PROVIDERS` if the invocation errors, with a unit test for the corrected command line.
- [ ] **Step 2: Cross-family measurement (~30 calls: 2 models × 3 readers × ~5 chunks).**

```bash
python3 scripts/sue_reproducibility.py specs/029-builder-spec-workbench/spec.md \
  --model-cmd claude --model-cmd codex=codex --json > h4-029.json
```

- [ ] **Step 3: Record** in the memo: within-family vs cross-family pairwise agreement (sidecar separates provider/model_tag per reader), and whether cross-family divergence concentrates on the known-defect requirements (the H4 signal). This satisfies the "heterogeneous model families" prerequisite (v4 debt 5a). Commit.

### Task 7: Critical-fact retention — scope closure (v4 debt 5b)

Retention is definitionally a multi-round property; v3 is single-round by design. Closure = surface the existing measure where it lives (dialectic) and scope the debt precisely, not build a fake metric.

**Files:**
- Modify: `docs/sue-usage.md` §4, `docs/superpowers/specs/2026-07-19-sue-v3-reproducibility-design.md` (addendum)

- [ ] **Step 1: Verify the dialectic JSON exposes retention** (`grep -n "RETENTION\|retention" scripts/sue_dialectic.py`): each `⚠ RETENTION` event must appear as a structured field (turn, abandoned evidence lines), not only as report text. If it is report-only, add the field to the JSON trace (+ unit test in `tests/unit/test_sue_dialectic.py` replaying a revision-that-drops-evidence trace).
- [ ] **Step 2: Document** in usage guide §4: retention is measured per-chain in Forensic tier; v3 deliberately has no multi-round retention (single-round instrument). Add the matching design-doc addendum line. Commit.

### Task 8: SRP corpus run — the original experiment (A1–A6 scorecard)

**Gated on Task 2 A1 PASS** (probe §5: "The corpus run proceeds only once A1 is met").

**Files:**
- Create: `probe/` harness per probe §10 (standalone; imports `understanding`, `harness.llm_provider` allowed — the probe harness is NOT under FR-045), mutation corpus with ground-truth labels, results report, decision memo

- [ ] **Step 1: Corpus selection.** 10–15 specs from `specs/` history that passed deterministic Understanding gates and have downstream outcomes (review-fix / `RF{n}-T*` counts) for P3. List them with their outcome counts in the corpus manifest.
- [ ] **Step 2: Mutation authoring.** For each spec, M1a/M1b/M2/M3/M4/M5 per the probe §4 operator table, one localized edit each, **site pre-screened** (clean spec defect-free at the site; latent defects found go to the manifest as found-defects and the site is excluded). Human-approve every mutant. Re-run the 34 deterministic metrics per mutant (P3 contingency table).
- [ ] **Step 3: Smoke first (3 specs × 6 variants, K=5, ~450 calls), then review cost before the full corpus.** Use `sue_reproducibility.py --passes 2` per variant as the measurement engine (glossary arm). Record all 8 probe measurements per §7, detection scored **per primary channel** (operator→channel matrix).
- [ ] **Step 4: Full corpus run** only if smoke cost ≤ estimate ×2 and A1 holds on corpus clean-controls. Produce: results report (8 measurements, variance decomposition, per-operator breakdown, A1–A6 scorecard) + decision memo (proceed / fix-extraction / halt) per probe §10.
- [ ] **Step 5: Commit** corpus, results, memo. This is the step that converts the research report's remaining hypotheses (P1–P4) into measured results.

### Task 9: Workflow integration (gated on Task 8 "proceed")

**Files:**
- Modify: `extension/workflow/definition.yaml` (`allowed_state_updates`: `sue_findings`), `extension/workflow/journal-entry-types.yaml` (new entry type), `extension/workflow/phases/phase3-consensus.md` (WHY3 evidence feed)

- [ ] **Step 1:** Declare `sue_findings` in `allowed_state_updates` for phase3-consensus (standing lesson: contract keys added only in Python get stripped on the agent path).
- [ ] **Step 2:** Add the journal entry type; wire the phase spec to read `semantic-reproducibility.json` stable-low + verified witnesses as WHY3 critical-issue evidence, with the probe's rule: *extraction instability alone must not block a spec*.
- [ ] **Step 3:** `bash scripts/bash/dry-run.sh` → extension wiring validates. Commit.

### Task 10: Documentation + memory closure

- [ ] **Step 1:** Sweep `docs/sue-usage.md` — every caveat must match measured state after Tasks 2–6 (SR absolute-or-comparative per A1 verdict; witness channel per Task 3; j-graph status per Task 4; codex flags per Task 6).
- [ ] **Step 2:** Update memory `sue-challenge-script.md`: measured noise floor, A1 verdict, H-D2 verdict, corpus status. Clear resolved "pending" clauses.
- [ ] **Step 3:** Final commit; the traceability table at the top of this plan must have every row's closing task either checked or carrying a recorded falsification.

---

## Execution order and cost envelope

```
Task 0 (gate) ─→ Task 1 ─→ Task 2 ─→ Task 8 ─→ Task 9
                     │          ├─→ Task 3 ─→ Task 5
                     │          └─→ Task 6
                     ├─→ Task 4 (independent of 1–3; needs Task 0 only for sue_jgraph.py reconciliation)
                     └─→ Task 7 (doc-scope; anytime after Task 0)
Task 10 last.
```

Live-call envelope (claude/codex `-p` calls): Task 0 ~30 · Task 2 ~120 · Task 3 reuses Task 2 · Task 4 ~6 + adjudication ~10 · Task 5 ≤8 · Task 6 ~30 · Task 8 smoke ~450 (full corpus ~2,700 — decide only after smoke). Everything before Task 8 totals ~200 calls; Task 8 full-corpus is the one genuinely expensive decision and has its own review gate.
