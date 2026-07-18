# Risks

## Synthesized Risks

| Risk | Evidence | Impact | Owner / Follow-up |
|------|----------|--------|-------------------|
| Silent isolation leak: user-scope claude context biases both rounds despite temp cwd | Design premise (IN-REQ-DDDD35B79FFA) contradicted by user-scope loading behavior (A-002, U-002, journal entry 5) | Questions/answers subtly contaminated; grounding rule ("the text testifies") silently violated — no crash, no signal | INVESTIGATOR marker-instruction spike; CARTOGRAPHER documents residual leak or adds suppression flags |
| JSON extraction fragility: plain `claude -p` stdout may never be clean strict JSON | Prior art needed stream-json + a backend layer (`ai_cli_backend`); one-retry budget makes systematic noise fatal (A-001, A-009, U-001) | Exit-3 fires constantly; the tool is unusable and the acceptance run fails | INVESTIGATOR spike before HOW; SENTINEL noisy-output fixtures |
| Flaky acceptance criterion: one live run must overlap three model-found issues | IN-REQ-760CA37F3F8F…D05A70A0F5B4 vs model nondeterminism (journal entry 8) | Correct implementation can fail acceptance; risk of post-hoc goalpost moving at FINALIZE | CARTOGRAPHER encodes tolerance (e.g. ≥1 named issue or bounded reruns) in the AC |
| Acceptance target drift: spec 029 is active and may be amended before the acceptance run | A-004 validated only at base commit ef2643c9; 029 listed active in prior-spec context | Known-issue anchors disappear; acceptance criterion becomes unsatisfiable | Re-verify 029 before the run; freeze a fixture copy if amended |
| Accidental harness coupling: importing `src/harness` breaks the standalone contract | A-003; boundaries.md NON-boundary; design non-goals (IN-REQ-D9CE68110258) | Stream-json/tool-policy/config-cascade coupling contradicts the stable-interface promise and breaks the stub seam | CODE REVIEWER gate: no `harness.*`/`echelon.*` imports; tests run without installed venv |
| Spec-content egress: challenged spec text is sent to the model provider via the claude CLI | boundaries.md external boundary + trust boundaries | Specs containing sensitive or personal data inherit the operator's claude session data-handling posture — a data-protection consideration if SUE is later run against confidential specs | CARTOGRAPHER: state the egress fact in the spec's limitations; operators decide per-spec suitability |
| Arbitrary command execution via `--claude-cmd` | boundaries.md trust boundaries | The seam executes any operator-supplied command; acceptable for a developer tool but must stay documented, never config- or network-sourced | CARTOGRAPHER documents as operator-trust boundary; GUARDIAN review at threat-model time |

## Knowledge Risks

| Area | Concentration Signal | Risk | Mitigation |
|------|----------------------|------|------------|
| Entire repo (incl. `scripts/` conventions) | Single active contributor in recent git history | Bus-factor 1 for design intent behind SUE and its conventions; design doc is the only durable rationale record | Keep the design doc + spec as the canonical record; report format and CLI usage documented in the script header per `scripts/` convention |
| claude CLI invocation expertise | Working knowledge of `claude -p` quirks lives in `src/harness/ai_cli_backend` code, not documentation | SUE re-derives that knowledge from scratch; spike findings could evaporate | INVESTIGATOR records CLI version, flags, and observed stdout shapes in the investigation report |

## Drift Risks

| Artifact Pair | Drift Signal | Impact | Route |
|---------------|--------------|--------|-------|
| Design doc vs claude CLI releases | CLI is externally versioned; `-p` semantics, context loading, and output shape can change under SUE | Isolation and extraction assumptions rot silently; exit-3 rate climbs | INVESTIGATOR pins validated CLI version; note drift check in spec limitations |
| Approved design doc vs squad spec | "Collapsed audit section" (IN-REQ-2D4902546481) already dropped by DISCOVER outputs | Spec written from staging artifacts alone would deviate from the approved design | WHY1 challenges against the design doc directly; CARTOGRAPHER restores the collapsed-rendering requirement |
| `specs/029-builder-spec-workbench/spec.md` vs acceptance criterion | Live spec vs criterion anchored to its current defects | Acceptance breaks if 029 is fixed first | Freeze fixture before acceptance if 029 changes |
