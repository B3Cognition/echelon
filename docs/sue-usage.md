# SUE — Socratic Understanding Engine: Usage Guide

Five standalone tools in `scripts/`, stdlib-only, no echelon imports. Each
challenges or measures a markdown/lexicon specification via isolated model
calls and writes its report(s) **beside the spec**. Nothing ever modifies the
challenged specification (a preflight guard also refuses to challenge a file
whose name equals the tool's own report filename).

## Shared behaviour (all five tools)

```
python3 scripts/<tool>.py <path/to/spec.md> [options]
```

- **Exit codes:** 0 = success (report written) · 1 = bad input (missing/empty
  spec, bad arguments, report-path collision) · 2 = model command not found ·
  3 = unusable model output after the corrective retry (raw dumps in
  `<spec-dir>/.sue-debug/`).
- **Model selection:** `--model-cmd [PROVIDER=]COMMAND` (alias `--claude-cmd`).
  Providers: `claude` (default; prompt on stdin), `codex`
  (`codex exec --ephemeral --skip-git-repo-check --sandbox read-only -`,
  prompt on stdin), `copilot` (prompt in argv — **exposed in process
  listings; explicit opt-in only, never for confidential specs**).
  When omitted: `ECHELON_LLM` (claude/codex only) → `CODEX_THREAD_ID`/`CODEX_CI`
  markers → `claude`.
- `--timeout SECS` per model call (default 300; raise for large specs).
- **Privacy:** spec content is sent to the model provider. Reruns overwrite
  the previous report (git the reports you want to keep).

## 1. `sue_challenge.py` — quick Socratic filter (v1)

*When:* fastest single opinion — “what can this spec not answer?”
*Cost:* 2 model calls (~1–3 min).

```
python3 scripts/sue_challenge.py specs/NNN/spec.md
python3 scripts/sue_challenge.py spec.md --questions 20 --timeout 600
```

Options: `--questions N` (cap, default 15) · `--model-cmd` · `--timeout`.
Output: `socratic-challenge.md` — findings (CONTRADICTED first, then
UNANSWERABLE) with quoted evidence lines + audit appendix of ANSWERED
(discarded) questions. One-reader sample: findings vary between runs; treat
as leads, not an enumeration.

## 2. `sue_consensus.py` — reproducible findings + elenchus (v2)

*When:* the pre-implementation gate — only defects confirmed by ≥2 isolated
readers count. *Cost:* ~8 calls (K×2 + 2).

```
python3 scripts/sue_consensus.py specs/NNN/spec.md
python3 scripts/sue_consensus.py spec.md --readers 5 --min-support 3 --no-elenchus
```

Options: `--readers K` (default 3) · `--min-support M` (default 2) ·
`--questions N` · `--no-elenchus` · `--model-cmd` · `--timeout`.
Output: `socratic-consensus.md` — stable findings (support counts, reader
variants, evidence, one validated follow-up chain each) + sampling appendix.
Read stable findings as real; the appendix as noise.

## 3. `sue_reproducibility.py` — measurement instrument (v3)

*When:* comparing specs or before/after edits; per-requirement worst-first
map. *Cost:* models × readers × ceil(units/20) calls.

```
python3 scripts/sue_reproducibility.py specs/NNN/spec.md
python3 scripts/sue_reproducibility.py spec.md --readers 3 --families REQ,FR,AC --json
# H4 cross-provider matrix (each model gets EVERY framing):
python3 scripts/sue_reproducibility.py spec.md --model-cmd claude --model-cmd codex=codex
```

Options: `--readers K` **per model** (total = models × K) · `--families`
(default REQ,FR,AC,NFR,ERR) · `--passes N` (repeat the whole measurement N
times for trustworthy per-requirement scores) · `--model-cmd` (repeatable) ·
`--json` · `--timeout`.
Outputs: `semantic-reproducibility.md` + `.json` (machine-readable; separates
`understanding` vs `proto_justification` per requirement).
Reading the measurement vector: global SR is stable (±0.002 A/B), per-run SR is
comparative. **Use `--passes 2+` to make per-requirement scores trustworthy** —
the report then gives each requirement's mean±stdev, the measured
**extraction-noise floor** (differences below it are noise, not signal), and the
**stable-low set** (low in *every* pass = the real fracture set; the ≥2-run
intersection is now native, no manual work). `thin_consensus` flags agreement
over thin content (vagueness is NOT rewarded); witness candidates are heuristic.
Lexicon-format specs get canonical GIVEN/WHEN situations (witness channel by
construction); markdown specs fall back to lottery mode (noted in report).

## 4. `sue_dialectic.py` — Socratic drill (Forensic, manual)

*When:* one stable finding deserves a deep interrogation — the chain names
the minimal missing decision and classifies the failure. *Cost:* ≤ max-turns
calls.

```
python3 scripts/sue_dialectic.py spec.md --lens euthyphro \
  --seed "which operators may enter row-edit mode" --target FR-001
```

Options: `--lens` (nine choices, below) · `--seed TEXT`
(**required** — the claim/term under examination; take it from a v2 stable
finding) · `--target ID` · `--max-turns N` (default 7) · `--model-cmd` ·
`--timeout`.
Lens choice — pick by the defect type the seed finding suggests:

| Lens | Socratic move | Drills |
|---|---|---|
| `euthyphro` | definitions/essence, examples-vs-definition | undefined or circular terms |
| `meno` | criterion of recognition/verifiability | unverifiable requirements |
| `parmenides` | consequences of claim and negation | contradictions, tolerated opposites |
| `cratylus` | naming/synonym stability | lexical drift, unstable vocabulary |
| `theaetetus` | knowledge as justified account | claims without derivable evidence |
| `sophist` | division, look-alikes, non-being | missing boundaries/exceptions (M3-shaped) |
| `gorgias` | rhetoric vs substance | persuasive-but-thin text (`thin_consensus`) |
| `republic` | role separation, who-does-what | permission/actor defects (FR-001 class) |
| `philebus` | measure and mixture | unquantified constraints ("fast", no bound) |
Outputs: `socratic-dialogue.md` + `.json` (auditable trace). Terminal states:
`RESOLVED` (claim survived, sharpened) · `APORIA_UNDEFINED` (no definition
constructible) · `APORIA_CONTRADICTED` (text supports incompatible answers) ·
`APORIA_UNDERDETERMINED` (multiple valid readings) · `BOUNDED_STOP` (limit —
not a verdict). `⚠ RETENTION` flags a revision that abandoned its evidence.
Status: experiment arm C — manual tool, NOT the automated graph source.

## 5. `sue_jgraph.py` — one-shot justification graph (pilot)

*When:* cheap whole-spec claims/conflict map; the chosen automated Reasoning
Graph candidate (instrumented pilot; H-D2 test pending). *Cost:* K calls.

```
python3 scripts/sue_jgraph.py spec.md
python3 scripts/sue_jgraph.py spec.md --readers 3 --focus "edit permissions"
```

Options: `--readers K` (default 3) · `--focus TEXT` · `--model-cmd` ·
`--timeout`.
Outputs: `justification-graph.md` + `.json` — per-reader claims (`stated`
require evidence lines; `derived` list assumptions) plus **consensus conflicts**
(contradictions independently found by ≥2 readers, anchored by evidence lines),
a **conflict-convergence rate**, unanimous count, and mean evidence
completeness. The consensus conflicts are the trustworthy contradictions;
convergence + completeness are the H-D2 reasoning-layer quality numbers.

## Recommended workflows

- **Quick sanity check of any spec:** v1. Triage its findings by hand.
- **Gate before implementation:** v2 → fix stable CONTRADICTED, then stable
  behavioural UNANSWERABLE → rerun v2 → stop when only definitional tail
  remains (document it in a Limitations section; findings never reach zero —
  converge severity, not count).
- **Deep-dive one gap:** v2 stable finding → dialectic seed (pick the lens by
  defect type).
- **Whole-spec conflict map:** j-graph; intersect ≥2 readers.
- **Measure/compare:** v3 twice, intersect per-requirement lows; compare SR
  only between runs of the same tool version and unit families.
- **Cross-provider (H4):** v3 with repeated `--model-cmd` once the codex CLI
  is installed (flags pending first live verification).
