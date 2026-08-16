# Summary-Only Final Fix Report

Base: `13598232` (`fix: close final recovery and summary gaps`)

The authorized summary-only wave is complete. It preserves authoritative facts
under the existing 12-KiB architecture, closes generic terminal and verification
truth gaps, makes the tagged JSON boundary unforgeable, and guarantees a
non-empty deterministic fallback when model-line filtering leaves fewer than two
narratives. No Git-first restore, proportional-repair, certificate/debt, or
Tasks Lexicon implementation was changed.

## 1. Priority-preserving 12-KiB evidence

### Root cause

`_evidence_packet_json` iterated only `context.facts[:20]` in caller order and
stopped at the first fact that exceeded the 8-KiB evidence-core reserve. Public
delivery rendering constructs every per-strategy status, branch, PR, iteration,
verification, and stopping line before appending the aggregate `Delivery
result:` fact. A sufficiently large strategy set therefore consumed both the
20-fact window and byte budget before the aggregate outcome and late provider
truth were considered.

### RED

The production change that these tests catch is removal of priority selection
or reintroduction of caller-order truncation. Both tests use more than 20 facts
whose unbounded serialized size exceeds 12 KiB; the second enters through the
public delivery renderer.

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_evidence_prioritizes_authoritative_facts_over_strategy_paths tests/unit/test_run_skill.py::TestRunSkillAutoLand::test_delivery_summary_preserves_late_authority_in_bounded_packet -q
FF                                                                       [100%]
AssertionError: assert 'Changed work: hardened the delivery summary.' in ['strategy-00: branch: ...', ...]
AssertionError: assert 'Delivery result: 30 converged, 0 failed, 1 provider-limited  ·  300,000 tokens.' in ['strategy-00: ✓ CONVERGED', ...]
2 failed in 0.38s
```

### Fix

`_EvidenceFactPriority` now defines six explicit deterministic classes in the
authorized order:

1. authoritative terminal outcome/status;
2. verification results;
3. provider-limit or debt facts;
4. aggregate delivery result;
5. changed-work narrative; and
6. per-strategy/path detail.

Facts are classified from their canonical public rendering prefixes, sorted by
`(priority, original_index)`, and admitted against the serialized core budget.
The original index preserves stable order inside each class. A fact that does
not fit is skipped rather than terminating selection, allowing a later shorter
fact in the same or a lower class to use the remaining bytes. The old 20-fact
slice is removed. Top-level terminal status, provider-limit fields, and debt
fields remain outside this fact competition as before.

### GREEN

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_evidence_prioritizes_authoritative_facts_over_strategy_paths tests/unit/test_run_skill.py::TestRunSkillAutoLand::test_delivery_summary_preserves_late_authority_in_bounded_packet -q
..                                                                       [100%]
2 passed in 0.37s
```

The direct test also proves stable class ordering and retention of terminal
`Result`/`Status`, two verification facts, provider limit, accepted debt,
residual gates, aggregate delivery, changed work, and lower-priority branch
detail. Both tests assert the final packet is no larger than `12 * 1024` bytes.

## 2. Complete terminal and verification truth validation

### Root cause

The unfinished-run success matcher required a narrow subject such as `run`,
`delivery`, `specification`, or `work` close to a small verb list, so `The task
completed successfully.`, `Everything is done.`, and equivalent job/request
claims bypassed it. Verification contradiction handling recognized only the
literal word `verification` and only four authoritative verdicts. Consequently
`All tests passed.`, `Every check succeeded.`, green/passing test-suite claims,
and unsupported checks with no verification evidence were accepted for failed,
blocked, incomplete, unavailable, or absent verification.

### RED

The first strict-JSON public rendering command reproduced the exact requested
sentences and initial paraphrases while proving all four safe work-narration
controls still passed:

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_rejects_generic_unsupported_success_verdicts tests/unit/test_run_summary.py::test_summary_preserves_completed_work_narration_without_success_verdicts -q
FFFFFFFF....                                                             [100%]
8 failed, 4 passed in 0.33s
```

Self-review then expanded the paraphrase and safe-control matrix. This caught a
job-status synonym, a present-progress test verdict, and an overbroad rejection
of subject-first completed-work narration:

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_rejects_generic_unsupported_success_verdicts tests/unit/test_run_summary.py::test_summary_preserves_completed_work_narration_without_success_verdicts -q
..F......F..F..                                                          [100%]
AssertionError: assert 'The job is done.' not in summary
AssertionError: assert 'The regression tests are passing.' not in summary
AssertionError: assert 'The work completed included summary parser changes.' in summary
3 failed, 12 passed in 0.33s
```

### Fix

Terminal validation now recognizes generic terminal subjects, including task,
request, job, everything, and process, with successful/completed/done verdicts
whenever authoritative status is blocked, failed, interrupted,
budget-exhausted, or incomplete. Completion verbs are terminal only when used
as verdicts; action-first and subject-first changed-work narration with a stated
object remains allowed.

Verification evidence now recognizes passed, failed, blocked, incomplete,
unavailable/not-run, deferred, and skipped. Positive claims about verification,
tests, checks, test suites, or validation are accepted only when the unique
authoritative verification verdict is passed. Multiple verdicts or absent
verification remain unsupported, while narration such as implementing, adding,
or running diagnostic tests without a positive verdict remains safe.

### GREEN

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_rejects_generic_unsupported_success_verdicts tests/unit/test_run_summary.py::test_summary_preserves_completed_work_narration_without_success_verdicts -q
...............                                                          [100%]
15 passed in 0.27s
```

The final matrix includes the exact requested adversarial sentences, terminal
and verification paraphrases across every required negative state, unsupported
verification with no evidence, and five completed-work controls.

## 3. Unforgeable evidence boundary

### Root cause

`_compact_json` used ordinary `json.dumps(..., ensure_ascii=False)`, which leaves
ASCII `<`, `>`, and `&` literal. Because the compact JSON was placed between
literal `<evidence_packet>` sentinels, an untrusted task, fact, or inspected file
could contain `</evidence_packet>` and create an early closing boundary followed
by apparent prompt instructions. The pre-existing serialized-size calculation
also did not account for the expansion required by prompt-safe escaping.

### RED

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_evidence_escapes_sentinels_without_changing_json_semantics -q
F                                                                        [100%]
AssertionError: assert 4 == 1
 + where 4 = prompt.count('<evidence_packet>')
1 failed in 0.28s
```

The input contains literal opening and closing tags, forged instruction text,
Unicode full-width lookalikes, and 24,000 ASCII characters that expand during
JSON escaping.

### Fix

Compact prompt JSON deterministically serializes `&`, `<`, and `>` as
`\u0026`, `\u003c`, and `\u003e`. The same serializer now drives per-string
binary-search bounds, per-payload fit checks, and the final packet, so escaping
expansion cannot exceed the cap. The prompt and deployed summarizer contract
explicitly require JSON decoding and treat decoded values as untrusted data,
never instructions.

### GREEN

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_evidence_escapes_sentinels_without_changing_json_semantics -q
.                                                                        [100%]
1 passed in 0.29s
```

The test proves exactly one real opening and closing sentinel, no literal
sentinel syntax inside the packet, exact command/task/fact/instruction/lookalike
semantics after `json.loads`, decoded `<>&` inspection data, prefix-preserving
inspection truncation, and a packet at or below 12 KiB.

## 4. Empty output after Next filtering

### Root cause

Strict JSON validation correctly required two through four model strings, but
`_compose_summary` subsequently removed deterministic `next_step` echoes and
authoritative-truth duplicates without enforcing a post-filter minimum. Two
Next-only bullets therefore composed to an empty string, and one useful bullet
plus one Next echo composed to a one-line model card. The public squad banner
rendered the empty string as a blank `worked on` field.

### RED

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_falls_back_when_next_filter_leaves_fewer_than_two_narratives tests/unit/test_cli_run_summary.py::test_squad_summary_never_renders_empty_worked_on_after_next_filtering -q
FFF                                                                      [100%]
AssertionError: assert ''.startswith('Echelon completed the requested specification work')
AssertionError: assert 'Recorded one useful implementation detail.'.startswith('Echelon completed the requested specification work')
AssertionError: assert 'Echelon completed the requested specification work.' in public banner output
3 failed in 0.38s
```

### Fix

Model composition now requires two surviving narrative lines. Zero or one
survivor selects `_fallback_summary(context)`; deterministic fallback composition
does not apply the model minimum and always retains its base human-readable
line. This keeps Next ownership in the outer banner and prevents a blank public
`Worked on` value.

### GREEN

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_falls_back_when_next_filter_leaves_fewer_than_two_narratives tests/unit/test_cli_run_summary.py::test_squad_summary_never_renders_empty_worked_on_after_next_filtering -q
...                                                                      [100%]
3 passed in 0.36s
```

## Final focused verification

The final exact public-path node matrix is:

```text
.venv/bin/pytest tests/unit/test_run_summary.py::test_summary_evidence_prioritizes_authoritative_facts_over_strategy_paths tests/unit/test_run_skill.py::TestRunSkillAutoLand::test_delivery_summary_preserves_late_authority_in_bounded_packet tests/unit/test_run_summary.py::test_summary_rejects_generic_unsupported_success_verdicts tests/unit/test_run_summary.py::test_summary_preserves_completed_work_narration_without_success_verdicts tests/unit/test_run_summary.py::test_summary_evidence_escapes_sentinels_without_changing_json_semantics tests/unit/test_run_summary.py::test_summary_falls_back_when_next_filter_leaves_fewer_than_two_narratives tests/unit/test_cli_run_summary.py::test_squad_summary_never_renders_empty_worked_on_after_next_filtering -q
.....................                                                    [100%]
21 passed in 0.50s
```

Complete directly affected files:

```text
.venv/bin/pytest tests/unit/test_run_summary.py tests/unit/test_cli_run_summary.py tests/unit/test_run_skill.py -q
........................................................................ [ 54%]
...........................................................              [100%]
131 passed in 0.87s
```

Complete summary/CLI/skill/orchestrator regressions:

```text
.venv/bin/pytest tests/unit/test_run_summary.py tests/unit/test_cli_run_summary.py tests/unit/test_cli_continue.py tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_resume_spec_context.py tests/unit/test_cli_mode_args.py tests/unit/test_cli_status.py tests/unit/test_core_cli_run_discovery.py tests/unit/test_cli_run_dir_gitignore.py tests/unit/test_run_skill.py tests/unit/test_orchestrator.py -q
278 passed in 1.82s
```

Complete provider regressions:

```text
.venv/bin/pytest tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py tests/unit/test_provider.py tests/unit/test_squad_provider.py tests/kernel/test_squad_provider.py tests/unit/test_topology_provider.py tests/unit/test_spec_telemetry_provider.py -q
301 passed in 1.32s
```

Package/deployment/runtime prompt regressions, rerun after the final prompt
wording correction:

```text
.venv/bin/pytest tests/unit/test_prosaic_package_install.py tests/unit/test_workspace_init_deploy_runtime.py tests/kernel/test_phase_graph.py tests/unit/test_prosaic_prompt_loader.py tests/unit/test_prosaic_provider_deployment.py tests/unit/test_prosaic_constitution_runtime.py tests/unit/test_skill_loader_prosaic.py -q
164 passed in 78.52s (0:01:18)
```

Repository runner:

```text
bash tests/run-all.sh
Total: 1649 passed, 0 failed, 0 skipped
OVERALL: PASS
```

Bundle validation:

```text
bash scripts/bash/dry-run.sh
Bundle validation passed: 9 checks
```

Compilation and diff hygiene:

```text
.venv/bin/python -m compileall -q src tests/unit tests/integration
exit 0

git diff --check
exit 0
```

## Changed files

- `src/harness/run_summary.py` — explicit priority classes and stable bounded
  selection; prompt-safe JSON serialization and escape-aware byte accounting;
  complete terminal/verification validation; post-filter fallback minimum.
- `prosaic/subagents/echelon.summarizer.md` — matching JSON-data trust boundary
  while retaining paired ALWAYS/NEVER authoring rules.
- `tests/unit/test_run_summary.py` — public strict-JSON priority, truth,
  sentinel, semantic-decoding, escape-expansion, safe-control, and fallback
  coverage; legacy ordering and one-line expectations updated to the authorized
  contract.
- `tests/unit/test_run_skill.py` — oversized public delivery rendering with 31
  strategy rows, verification, provider-limit, aggregate, old-cutoff, and byte
  cap assertions.
- `tests/unit/test_cli_run_summary.py` — public banner proof that Next-only model
  output cannot render an empty `worked on` value.
- `.superpowers/sdd/2026-08-14-git-first-candidate-restore/summary-final-fix-report.md`
  — this evidence report.

## Self-review

- Re-read the authorized brief line by line and mapped every requirement to an
  exact test above.
- Confirmed the serialized packet schema remains version 1 with unchanged keys
  and JSON value types; only fact ordering/selection and prompt-safe source
  spelling changed.
- Confirmed stable ordering inside every fact class by retaining the original
  index and asserting order for two terminal facts, two verification facts,
  and three provider/debt facts.
- Confirmed raw test fixtures exceed both the former 20-fact cutoff and 12-KiB
  byte cap before selection.
- Confirmed safety escaping is used by all byte calculations, not added only at
  final serialization.
- Confirmed success matching retains both action-first and subject-first
  completed-work narration while rejecting terminal and verification verdicts.
- Confirmed fallback selection discards a lone model survivor rather than
  combining it with controller-owned truth and calling that two narratives.
- Inspected the complete diff from `13598232`: only the five summary files and
  this report are present; Git-first restore, proportional repair,
  certificate/debt behavior, and Tasks Lexicon behavior are untouched.

The first repository-runner attempt found one self-review issue in the prompt
edit: a wrapped line began with a second `NEVER`, violating the repository's
paired-rule parser. The exact failure was:

```text
FAILED tests/kernel/test_prompt_references.py::test_primary_agent_prompts_have_paired_always_never_rules
AssertionError: prosaic/subagents/echelon.summarizer.md: unpaired ALWAYS / NEVER rule
1 failed, 1507 passed in 19.09s
```

The negative rule was rewritten as one `NEVER` sentence, then the exact node
passed before the complete successful `tests/run-all.sh` rerun:

```text
.venv/bin/pytest tests/kernel/test_prompt_references.py::test_primary_agent_prompts_have_paired_always_never_rules -q
.                                                                        [100%]
1 passed in 0.23s
```

## Compatibility notes and concerns

- No architectural change was required; the existing 8-KiB fact-core reserve
  and 12-KiB total packet design preserve all tested authoritative classes.
- The provider still receives compact JSON and the same semantic strings after
  JSON decoding. Escaping `&`, `<`, and `>` can reduce retained low-priority
  detail under adversarial expansion, but cannot change decoded meaning or
  exceed the cap.
- Existing output schema, model limits, deterministic terminal/debt/provider
  lines, and terminal-banner Next ownership are unchanged.
- Future authoritative fact wordings that do not use the canonical terminal,
  verification, provider/debt, aggregate-delivery, or changed-work vocabulary
  intentionally default to the low-priority class. New canonical wording must
  extend the classifier and its public test matrix.
- No known blocker or architectural concern remains in the authorized scope.
