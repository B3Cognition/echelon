# Phase: phase1-lexicon-derive

## Purpose

Produce or repair the controlled-grammar projection of the current,
quality-certified `spec.md`.

## Actor

`echelon.lexicon-deriver`

## Required Inputs

- `{spec_dir}/spec.md`
- `{spec_dir}/glossary.md`, when present
- injected `Controller Configuration`
- `{spec_dir}/spec-lexicon-report.json`, on repair

## Required Output

- `{spec_dir}/requirements.lexicon.md`

No other artifact is writable in this phase.

## Procedure

1. Read the controller-supplied source, paths, glossary, and repair findings.
2. Derive or regenerate `requirements.lexicon.md` from the exact source.
3. Preserve every source identifier and emit current source metadata.
4. On repair, resolve every reported finding without editing the canonical
   source.
5. Return the single output using the declared result contract.

## Controlled Grammar Reminder

The derived file is parsed literally. A `REQ:` block contains `GIVEN:`,
`WHEN:`, `THEN:`, required `OUTPUT:`, optional `CONSTRAINT:` / `DEPENDS:`, and
an `EXAMPLE:` link to a source acceptance criterion. Start the file with literal
`# SOURCE:` and `# SOURCE_SHA256:` metadata, followed by the `ARTIFACT:` and
`TITLE:` header. An `AC: <AC-id>` block contains only `GIVEN:`, `WHEN:`,
`THEN:`, and optional `CONSTRAINT:` lines. `AC:` blocks MUST NOT contain
`OUTPUT:`, `EXAMPLE:`, or `DEPENDS:`. Keep an acceptance criterion's observable
outcome in its `THEN:` line.

The provider-free `phase1-lexicon` node performs structural certification after
this dispatch.

## Failure

If the canonical source cannot be translated without changing its meaning,
return `FAIL` with the exact source location and make no source changes. The
controller fails closed; this phase cannot reopen general specification
authoring by itself.

## Transition

Successful derivation proceeds to `phase1-lexicon`.
