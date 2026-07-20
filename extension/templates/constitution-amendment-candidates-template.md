# Constitution Amendment Candidates Template

Use this template for `{spec_dir}/constitution-amendment-candidates.md`. This is a proposal-only artifact: it never changes the canonical constitution and requires human review through `speckit.constitution`.

## Metadata

| Field | Value |
| --- | --- |
| Spec / run | `<spec-id> / <run-id>` |
| Current constitution version | `<version or snapshot>` |
| Proposed by | `<ARCHITECT / MIRROR / VETERAN>` |
| Status | `PROPOSED — human decision required` |

## Candidate Register

| ID | Proposed Principle | Source | Evidence | Confidence | Status |
| --- | --- | --- | --- | --- | --- |
| `CA-NNN` | `<short principle>` | `<ADR, feedback, or journal reference>` | `<supporting evidence>` | `<low / medium / high>` | `PROPOSED` |

## Candidate Detail: CA-NNN

- **Current rule or gap:** `<relevant constitution text, or no existing rule>`
- **Proposal:** `[PROPOSED: <principle text>]`
- **Motivating evidence:** `<ADR, implementation result, or recurring feedback>`
- **Impact if adopted:** `<teams, artifacts, or decisions affected>`
- **Trade-offs / conflicts:** `<conflicting principle or none>`
- **Human decision requested:** `<approve, revise, or reject>`

Repeat this section for every candidate requiring context beyond the register.

## Decision Protocol

CHIEF and the human owner decide whether to amend the canonical constitution. Preserve rejected and deferred candidates here as review history; do not promote them automatically.
