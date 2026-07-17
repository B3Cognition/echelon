# Optional Understanding Diagrams

## Problem

SAGE automatically generates SVG and PNG behavioral diagrams during WHY2 and
WHY3 validation. These diagrams are a human-facing aid rather than an input to
spec generation or a quality gate. On large specifications, Graphviz can time
out and trigger retries, delaying an otherwise successful validation run.

## Decision

Automatic behavioral-diagram generation is opt-in. Add this configuration to
the shipped Echelon defaults and template:

```yaml
understanding:
  diagram:
    enabled: false
```

SAGE reads `understanding.diagram.enabled` before the behavioral-diagram step.
When the value is not explicitly `true`, SAGE skips the diagram skill, Graphviz
execution, diagram retries, and `diagram_skipped` journal entry. An intentional
configuration skip is not an operational failure.

The standalone `echelon understanding-diagram` command remains available and
is unaffected. A user can therefore request a diagram explicitly without
enabling automatic generation in WHY2 and WHY3.

When automatic generation is enabled, the existing behavior remains intact:
SAGE requests both `spec-diagram.svg` and `spec-diagram.png`, treats generation
failure as non-blocking, and reports genuine failures through the existing
`diagram_skipped` journal entry.

## Implementation Boundaries

- Add the default-off setting to `extension/config-template.yml` and
  `extension/echelon-config.yml`.
- Update SAGE's invariant protocol and its Understanding follow-up appendix so
  automatic generation is conditional on the setting.
- Keep the explicit diagram command and the Understanding CLI unchanged.
- Do not add timeout, retry, output-format, or Graphviz tuning settings.

## Verification

Static contract tests will assert that both shipped configurations default the
setting to `false`, that SAGE reads the setting before invoking diagram
generation, and that the explicit diagram command remains present. Existing
SAGE Understanding contract tests must continue to pass.
