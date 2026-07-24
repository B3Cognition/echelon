# Controller-Owned CARTOGRAPHER Validation Design

## Goal

Resolve issue #176 by removing provider-dependent validation commands and configuration probes from the canonical CARTOGRAPHER prompts while preserving the existing Phase A artifact, validation, repair, and routing behavior.

## Prompt Contract

Canonical Markdown prompts describe the agent's role, supplied context, artifact responsibilities, constraints, and exact `echelon_result` shape. They do not tell the model to invoke Echelon CLIs, discover configuration, inspect runtime installation details, or certify deterministic verdicts.

The prose uses direct instructions, descriptive Markdown headings, concise XML-delimited dynamic context where the harness injects machine-owned data, and explicit examples only where an output grammar benefits from one. Instructions and context remain visibly separate. The same canonical prompt must work with Claude CLI, OpenAI-compatible APIs, and future artifact-capable providers.

## Ownership

### CARTOGRAPHER

- Authors and amends the rich `spec.md` and `00-overview.md` artifacts.
- When the injected Lexicon mode is enabled, authors or repairs the derived requirements artifact using the supplied grammar and controller findings.
- Reports only authoring status and the allowed phase result fields.
- Does not run Understanding, Lexicon, shell, or Python validation commands.
- Does not read Echelon configuration files or claim deterministic pass/fail verdicts.

### Harness

- Resolves the effective Lexicon configuration through `get_full_resolved_config`.
- Injects a concise phase-specific configuration block into CARTOGRAPHER prompts.
- Executes the visible, provider-free `phase1-lexicon` node after every successful `phase1-what` dispatch.
- Writes a structured report containing the effective paths, result, and complete findings.
- Owns `lexicon_evaluation`, `lexicon_pass`, `lexicon_findings`, report path, and repair-attempt accounting.
- Injects the failed report path and concise repair instructions into the next CARTOGRAPHER dispatch.
- Runs Understanding in the existing deterministic `phase1-understanding` node.
- Performs artifact/status checks at the controller boundary rather than asking the model to execute shell snippets.

## Data Flow

1. The harness resolves the effective spec Lexicon subgate.
2. The prompt receives a `# Controller Configuration` section with `enabled`, artifact type, derived path, source path, glossary path, and repair limit. Dynamic values are rendered as data, not instructions.
3. CARTOGRAPHER writes the required artifacts and returns the strict phase result block.
4. The provider-free `phase1-lexicon` node validates the exact on-disk derived artifact and writes `<spec_dir>/spec-lexicon-report.json` atomically.
5. A passing report clears the attempt counter and permits transition to `phase1-understanding`.
6. A failed report increments the controller-owned attempt counter and routes back to `phase1-what` while injecting the report path.
7. A missing artifact or validator execution error remains `pending` and cannot manufacture a failed verdict. Existing exhaustion policy remains authoritative.

## Report Contract

The JSON report contains:

- `schema_version`
- `artifact_type`
- `artifact_path`
- `source_path`
- `glossary_path`
- `artifact_sha256`
- `source_sha256`
- `glossary_sha256`
- `ok`
- `findings[]`, with `code`, `message`, `line`, and `span` when available

The state stores only the report path and concise routing fields. Full findings stay in the report to avoid bloating every model turn.

## Compatibility And Migration

The phase graph exposes `phase1-lexicon` between `phase1-what` and `phase1-understanding`. Existing valid artifacts pass through both deterministic nodes without a provider dispatch. Existing active Phase A artifact runs without current content-bound Lexicon evidence are routed through `phase1-lexicon`; legacy hard-gate blocks resume there as well. Agent-authored stale validation fields cannot override controller evidence.

The tasks Lexicon gate remains unchanged. The spec gate adopts its established report-and-repair-context pattern where practical.

## Testing

- Controller tests prove complete report persistence, attempt accounting, pending semantics, resolved local configuration, and repair redispatch.
- Executor tests prove configuration and failed-report context are injected only where relevant.
- Prompt tests reject `understanding scan`, `lexicon validate`, Python config probes, and shell verification snippets in CARTOGRAPHER and `phase1-what`.
- Flow tests prove `phase1-what -> phase1-lexicon -> phase1-understanding -> phase1-why2` remains intact on pass and bounded redispatch remains intact on failure.
