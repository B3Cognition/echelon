# Element identity artifact adapters

`harness.element_artifacts.parse_identity_artifact` is a read-only parser for
controller-classified specification artifacts. It reports source facts with
exact Python string offsets and a SHA-256 digest of the original UTF-8 bytes.
It never opens the supplied path, writes files, allocates identifiers, or
changes controller storage.

## Role ownership

The controller supplies one exact role for each artifact:

| Role | Declaration authority | Disposition |
| --- | --- | --- |
| `unknowns` | `### U-…: Caption` heading block | `definition` |
| `assumptions` | `### A-…: Caption` heading block | `definition` |
| `requirements` | FR, NFR, or AC ID headings and top-level ID bullets | `definition` |
| `tasks` | Canonical task row with exactly one subordinate `**Title:**` | `definition` |
| `issues` | `### ISS-…: Caption` review occurrence | `occurrence` |
| `lexicon` | Valid whole-document Lexicon FR/NFR `REQ` and AC blocks | `definition` |
| `lexicon_projection` | The same validated Lexicon blocks in a derived artifact | `projection` |
| `investigation` | References only | none |
| `evidence` | References only | none |
| `references` | References in ordinary active Markdown | none |

An issue heading is an observed review occurrence until a later controller
operation binds it to a durable issue. A `lexicon_projection` declaration is a
derived representation of an existing entity, not fresh declaration
authority. A declaration's `caption` is its rendered source title; it is not
an immutable registry subject.

## Source and reference rules

Heading blocks end at the next heading of the same or higher level. The known
`### Resolution Guidance` companion remains inside an issue occurrence, while
an unrelated same-level heading and report footer remain outside it. ID bullets
and task rows own indented continuation content and internal blank lines, but
not the next nonblank unindented block.

HTML comments, frontmatter, matching backtick or tilde fences, blockquotes, and
indented code do not carry declaration or reference authority. Inline code
remains active, so a local path such as `investigation/U-001.md` retains the
exact `U-001` reference. Numeric ranges use one interval reference and are
never expanded. Task `req=` and `depends=` references are classified as
`requires` and `depends`; `INFRA`, `UNMAPPED`, and `none` are metadata
sentinels rather than element IDs. Investigation and evidence references have
the `evidence` relation, but that relation does not verify evidence or bind it
to any revision.

The parser preserves duplicates and exact source order. It recognizes legacy
numeric widths, arbitrarily large ASCII numeric labels, and supported ASCII
composite suffixes without prefix truncation. Range ordering uses the shared
unbounded decimal conversion and retains the two exact endpoints.

## Diagnostics

Diagnostics cover invalid or unterminated artifact syntax, malformed task
rows and titles, unsupported declaration forms, wrong-role definitions,
ambiguous nested declaration boundaries, invalid ranges, unsupported Lexicon
families, managed IDs placed in non-entity Lexicon blocks, and duplicate
definitions, projections, or occurrences. Explicit qualified references such
as `specs/002-other/spec.md#FR-001` and `002-other::FR-001` are diagnosed:
this checkpoint has local-spec identity only and has no cross-spec namespace
resolver.

A caller must treat any diagnostic as making the artifact unsuitable for
future managed publication. Discarding diagnostics and claiming validation is
not supported.

## Deliberate boundary

This adapter is a parser checkpoint only. It does **not** enforce publication.
Registry subject selection, assessed revision, active versus historical
status, namespace resolution, cross-artifact padding-alias conflicts,
edit-scope permission, lifecycle authorization, publication compare-and-swap,
durable reference binding, and evidence verification all belong to later
controller validation and publication checkpoints.
