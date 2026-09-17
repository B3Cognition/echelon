# Element artifact adapters implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Parse identity-bearing artifacts without confusing declarations, derived representations, issue occurrences, and references.

**Architecture:** Pure typed adapters preserve source spans, exact labels, duplicate declarations, and reference provenance. The caller supplies the artifact role; arbitrary journal quotations cannot become identity authority. These adapters do not allocate, mutate the registry, certify evidence, or publish files. Candidate validation and publication integration consume their results in subsequent checkpoints.

**Tech Stack:** Python dataclasses, existing Lexicon grammar and canonical task-row parser, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Preserve exact published labels. Six digits is a minimum for newly allocated labels, not a parser width limit. Never allocate or renumber in an adapter.
- Distinguish definitions from references; never deduplicate before duplicate-definition validation.
- A content hash is an integrity/revision binding, not semantic identity or evidence of semantic equivalence.
- The seven managed families are AC, FR, NFR, ISS, U, A, T. Explicit unsupported declarations must be reported, not silently dropped or heuristically reinterpreted.
- Keep existing legacy readers and `issue_identity.py` behavior unchanged. This checkpoint remains inactive in orchestration.

---

### Task 1: source-preserving typed artifact adapters

**Files:** Create `src/harness/element_artifacts.py` (immutable models, role routing, public entry point), `src/harness/element_artifact_markdown.py` (source scanning and Markdown declarations/references), `src/harness/element_artifact_lexicon.py` (validated grammar projection); create `tests/unit/test_element_artifacts.py`, `tests/unit/test_element_artifact_lexicon.py`, sanitized fixtures under `tests/fixtures/element_identity/discovery/`, and `docs/element-identity-artifacts.md`. Reuse `kernel.task_contract.parse_task_rows` and `lexicon.parser.parse`; do not change those public legacy APIs. Only introduce additional focused helpers if required to avoid a large mixed-responsibility module.

**Inputs and interfaces:**

```python
@dataclass(frozen=True)
class ArtifactSpan:
    start: int                 # Python string offset, inclusive
    end: int                   # exclusive, exact source slicing
    line: int                  # one-based first line

@dataclass(frozen=True)
class ElementDeclaration:
    element_id: str
    kind: str
    caption: str               # rendered title, NOT registry subject authority
    content: str               # exact source block, including declaration
    span: ArtifactSpan
    label_span: ArtifactSpan
    disposition: str          # definition | projection | occurrence

@dataclass(frozen=True)
class ElementReference:
    target_id: str             # exact label, or exact first label for a range
    range_end_id: str | None   # retained interval, NEVER eagerly expanded
    span: ArtifactSpan         # full single reference or full range
    owner_id: str | None       # containing declaration, if any
    relation: str              # reference | requires | depends | evidence

@dataclass(frozen=True)
class ArtifactDiagnostic:
    code: str
    span: ArtifactSpan
    detail: str

@dataclass(frozen=True)
class ParsedIdentityArtifact:
    path: str
    role: str
    content_sha256: str
    declarations: tuple[ElementDeclaration, ...]
    references: tuple[ElementReference, ...]
    diagnostics: tuple[ArtifactDiagnostic, ...]

def parse_identity_artifact(*, path: str, role: str, text: str) -> ParsedIdentityArtifact:
    ...
```

Source spans must slice the original string exactly, including CRLF/Unicode inputs. Return diagnostics for artifact syntax/unsupported declaration problems; invalid API types, roles, noncanonical relative paths, NUL or unencodable input raise `ValueError`. Never open paths or perform writes. Results and their nested collections are immutable. `content_sha256` covers original UTF-8 bytes, not normalized text.

The roles are controller-supplied exact strings:

| Role | Identity-bearing form | Disposition |
| --- | --- | --- |
| `unknowns` | Heading `### U-001: Question` with its subordinate block | definition |
| `assumptions` | Heading `### A-001: Title` with its subordinate block | definition |
| `requirements` | Markdown ID bullet such as `- **FR-001**: Statement`, `AC`/`NFR` equivalents, or ID heading block | definition |
| `tasks` | Canonical task row with subordinate task block and `**Title:**` | definition |
| `issues` | `### ISS-001: Title` plus fields and subordinate resolution guidance | occurrence |
| `lexicon` | Whole valid Lexicon document, `REQ:` using FR/NFR and `AC:` using AC | definition |
| `lexicon_projection` | Same grammar, derived representation of existing entities | projection |
| `investigation` | No declarations; source questions, unknowns, linked questions and referenced IDs | evidence references |
| `evidence` | No declarations; evidence-grade table and referenced IDs | evidence references |
| `references` | No declarations; supported IDs in ordinary active Markdown text | reference |

The distinction between `requirements` and `lexicon_projection` is necessary because Echelon authors `spec.md` and separately derives `requirements.lexicon.md`. The same FR label in these two artifacts is not two new entities. An issue heading is a review occurrence until the controller binds it to a durable issue; parsing the heading does not allocate that issue.

**Source/block rules:**

1. For headings, a declaration block ends before the next heading of the same or lower level; subordinate headings remain inside it. Thus `### Resolution Guidance` is inside an ISS occurrence only when it is the known issue companion section; the next `### ISS-...` or `##` ends the occurrence. A plain unrelated same-level heading ends it. Preserve the original slices and do not swallow report footers.
2. ID-bearing Markdown bullets own their indented continuation lines, nested lists and internal blank lines, ending before the next nonblank unindented block. Canonical task rows use the same boundary with a required subordinate title. A malformed task-looking row or missing/duplicate title is a diagnostic, not an invisible omission. Reuse the canonical parser for row validity and metadata; retain every row before duplicate checks.
3. Ignore HTML comments, frontmatter, fenced code examples (backtick and tilde fences, matching delimiter/length), blockquotes and indented code as authority. Lexicon is a whole-document explicit role, not a heuristic interpreting a quoted code example as declarations. Unterminated comments/fences/frontmatter or ambiguous ID-bearing block boundaries produce diagnostics instead of hiding the rest of an artifact. Inline code does not suppress references: `investigation/U-001.md` is a real referenced label in these artifacts.
4. Detect explicit declaration-shaped known managed IDs in the wrong role/type and return `unexpected_definition`. Reference-only rows/cells in `spec.md` open-question and assumption summaries are references, not extra definitions. Do not mistake a sentence beginning with an ID mention for a heading/bullet declaration.
5. Retain duplicates in source order; additionally emit `duplicate_definition` for repeated definition labels within an artifact. Do not treat repeated references as duplicate definitions. Projection/occurrence duplicates also produce a role-specific diagnostic rather than collapsing them.
6. Preserve numeric legacy labels, seven-plus-digit labels, and supported ASCII composite suffixes exactly. Detect full tokens, including suffix boundaries: FR-001a is not FR-001, and FR-1000000 is not a shorter prefix. Wrong-family or unsupported Lexicon REQ/AC IDs are diagnostics. Other grammar blocks such as RULE/ERROR remain outside these seven families and cannot create a managed entity; a managed-looking declaration ID in one is diagnostic.
7. References exclude only the declaration's own label span, not all occurrences of that label elsewhere in its body. Parse `req=` and `depends=` as `requires`/`depends`; INFRA, UNMAPPED and none are task metadata sentinels, not entity IDs. Evidence/investigation references are `evidence`; this classification alone never makes them verified or attaches them to a current revision.
8. Retain same-kind numeric ranges such as `U-001–U-005`, `U-001—U-005`, `U-001..U-005`, and `U-001 - U-005` as one interval reference. Validate nondecreasing canonical numeric endpoints with the shared unbounded decimal conversion helper; do not expand even a million-wide range. Malformed/reversed/cross-kind ranges return diagnostics and must not silently become two independent references. Comma-separated references remain separate. Path references retain exact labels. Opaque composite labels are not numeric intervals.
9. The adapter reports source facts only. Registry subject, assessed revision, active/historical status, namespace resolution, padding-alias conflicts across artifacts, edit-scope permission, lifecycle authorization, and publication CAS belong to subsequent validation. Document this boundary explicitly.
10. This initial reference model is local-spec only. Explicit qualified references such as `specs/002-other/spec.md#FR-001` and `002-other::FR-001` produce `unsupported_qualified_reference` diagnostics rather than silently resolving as local FR-001. Ordinary local `investigation/U-001.md` remains supported. A future namespace adapter may add qualified resolution; this checkpoint must expose, not guess at, unsupported qualification.

**Step 1 — RED:** Add these concrete tests before implementation, plus cases for the rules below.

```python
def test_question_declaration_and_evidence_reference_are_distinct():
    questions = parse_identity_artifact(
        path="unknowns.md", role="unknowns",
        text="### U-001: Keyboard focus ownership\n\n- Why: focus must return to the game.\n",
    )
    evidence = parse_identity_artifact(
        path="evidence-grades.md", role="evidence",
        text="| E3 | U-001 | activeElement | A | Focus ownership |\n",
    )
    assert [d.element_id for d in questions.declarations] == ["U-001"]
    assert questions.declarations[0].caption == "Keyboard focus ownership"
    assert not evidence.declarations
    assert [(r.target_id, r.relation) for r in evidence.references] == [("U-001", "evidence")]

def test_duplicate_declarations_are_not_collapsed():
    text = "- **AC-000001**: Move.\n- **AC-000001**: Stop.\n"
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert len(result.declarations) == 2
    assert "duplicate_definition" in {d.code for d in result.diagnostics}
    for declaration in result.declarations:
        assert text[declaration.span.start:declaration.span.end] == declaration.content

def test_derived_lexicon_is_not_an_independent_definition():
    text = ("ARTIFACT: SPEC\nTITLE: Game\n\nREQ: FR-000001\n"
            "GIVEN: an active player\nWHEN: movement is requested\n"
            "THEN: the game MUST move the player\n\n"
            "AC: AC-1000000\nGIVEN: an active player\n"
            "WHEN: movement is requested\nTHEN: the player position changes\n")
    result = parse_identity_artifact(path="requirements.lexicon.md", role="lexicon_projection", text=text)
    assert [(d.element_id, d.disposition) for d in result.declarations] == [
        ("FR-000001", "projection"), ("AC-1000000", "projection")]
    assert not result.diagnostics
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifacts.py tests/unit/test_element_artifact_lexicon.py -q`; capture the expected missing-interface failure.
- [ ] Add source-span, malformed-input, wrong-role, duplicate, full-token/suffix, giant interval, task metadata/title, issue companion/footer, comment/fence/frontmatter/quote, CRLF and Unicode tests before the corresponding behavior. Include valid existing Markdown/task/Lexicon template examples and ensure unsupported legacy Lexicon labels yield diagnostics instead of disappearing.

**Step 2 — implement incrementally:** Route only explicit roles, scan source offsets without mutating input, construct declarations first, then extract references outside their declaration-label spans. Validate Lexicon with the existing grammar before projecting REQ and AC source blocks. Existing parser trees need not gain a new global configuration: a local source-span pass may align validated block boundaries with the original text. It must retain order/duplicates and include every REQ/AC block, not reuse requirement projection that deliberately omits ACs.

```python
def parse_identity_artifact(*, path, role, text):
    validate_input(path, role, text)
    # The helpers are private to the focused adapter modules.
    if role in {"lexicon", "lexicon_projection"}:
        declarations, references, diagnostics = parse_lexicon_source(text, role)
    else:
        declarations, references, diagnostics = parse_markdown_source(text, role)
    return ParsedIdentityArtifact(
        path, role, hashlib.sha256(text.encode("utf-8")).hexdigest(),
        tuple(declarations), tuple(references), tuple(diagnostics),
    )
```

- [ ] Create sanitized minimal `before/unknowns.md`, `after/unknowns.md`, and retained `evidence-grades.md` fixtures using only these established facts: old U-001 visual style, U-002 collision margin, U-003 DOM status, U-004 focus ownership, U-005 large-step collision; repaired U-001 map dimensions/speed, U-002 graphics fallback, U-003 focus conveyance, U-004 initial placement, with U-005 absent. Evidence still cites the old U-003/U-004 and U-001/U-002/U-005 subjects. The fixture test must show the changed captions, removed declaration and retained references. It must NOT claim publication rejection yet. Do not access or change the stopped workspace.
- [ ] Document role ownership, supported syntax, diagnostics and deliberate limitations. A diagnostic makes an artifact unsuitable for future managed publication; callers must not discard diagnostics and claim validation.

**Step 3 — GREEN and review:**

- [ ] Run the new adapter suites plus `tests/unit/test_tasks_canonical_contract.py`, `tests/unit/test_lexicon_parser.py`, `tests/unit/test_requirement_projection.py`, and `tests/unit/test_issue_identity.py`. No provider calls or whole-unit suite needed for this pure new layer.
- [ ] Run `git diff --check`; self-review full-token matching, source ownership boundaries and unsupported-syntax paths.
- [ ] Commit only task files and report exact RED/GREEN evidence. State clearly that this is a parser checkpoint, not publication enforcement or live rollout.

## Coverage and following checkpoints

This plan implements the typed artifact-adapter part of the approved design. Durable reference/issue-occurrence bindings, history-aware import/audit tools, canonical candidate validation, publication intents and recovery, graph/memory projection, all managed producers, bounded discovery repair, and the offline/live verification checkpoints remain separate required work. A derived representation must be validated against the bound canonical revision before it can certify anything.
