# Identity reference token boundaries implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent a longer unsupported identity or a nonlocal locator from being accepted as a shorter local reference, while retaining documented sentence, interval and investigation-locator syntax.

**Architecture:** One source-preserving lexical pass classifies whole reference tokens before relation/owner assignment. Supported identity grammar remains unchanged; unsupported labels, malformed intervals and unresolved locators produce explicit diagnostics. Existing candidate and history consumers inherit rejection without changing their storage or authority contracts.

**Tech Stack:** Existing Python typed artifact adapters and pytest; no dependencies, schema or public data-model changes.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- Unsupported composite legacy formats remain opaque reserved identities; migration must not reinterpret them heuristically.
- Historical evidence is retained, not relabeled as proof of the new content.
- Typed adapters distinguish definitions from references in supported Markdown, task rows, Lexicon, and investigation artifacts.
- No allocation, import, lifecycle, schema, binding receipt, publication, provider or managed-activation changes in this task.

---

### Task 1: source-preserving whole-token reference classification

**Files:** Create `src/harness/element_artifact_reference_tokens.py` and `tests/unit/test_element_artifact_reference_tokens.py`. Modify `src/harness/element_artifact_markdown.py` to use the scanner, `tests/unit/test_discovery_identity_candidate.py` and `tests/unit/test_element_identity_history.py` for inherited-rejection tests, and `docs/element-identity-storage.md` for the lexical contract. Existing artifact tests must continue to pass unchanged. `element_artifact_lexicon.py` may only need import adjustments if shared constants move; keep its grammar/validation/relation behavior unchanged.

**Interfaces:** Keep `parse_identity_artifact`, `ElementReference`, their fields and exact span semantics unchanged. Introduce this internal pure interface:

```python
@dataclass(frozen=True)
class ReferenceToken:
    start: int
    end: int
    target_id: str | None = None
    range_end_id: str | None = None
    diagnostic_code: str | None = None
    detail: str = ""

def scan_reference_tokens(text: str, *, active: bytearray,
                          excluded_spans: Sequence[tuple[int, int]]) -> tuple[ReferenceToken, ...]:
    """Classify complete visible references without IO or source mutation."""
```

Each result is either one supported singleton/interval or one diagnostic, never both. Return source order; no overlapping tokens and no independent reference extracted from within a rejected token/interval/locator. Respect the existing active-source mask and declaration-label/unsupported-declaration exclusions; do not mutate them, concatenate across excluded source, or manufacture source offsets. Inactive frontmatter, fenced/indented code, comments and quotes remain inactive. Inline code remains active for references.

Move the shared `_ID_CORE`, `_NUMERIC_OR_COMPOSITE`, `_TASK_VALUE` constants into the new module if needed, importing them back under the existing private names used by Markdown/Lexicon. Do not duplicate the supported grammar. Keep definition parsing unchanged. The Markdown `_references` function remains the relation/innermost-owner adapter and converts scanner tokens into existing `ElementReference` / `ArtifactDiagnostic` objects. Remove the superseded independent reference-regex passes instead of keeping two competing interpretations.

**Lexical contract (deliberately narrower than the opaque registry envelope):**

1. Successful labels retain the existing complete numeric/composite grammar, including `AC-001a`, `FR-001abc`, `T-S01` and arbitrarily wide decimal values. Match the whole label, not a successful prefix. An identity-shaped token starts with one of the seven managed family prefixes followed by an ASCII letter/digit. Adjacent suffix characters such as `.other`, `-extra`, `_extra`, Unicode letters and internal `*`/backticks belong to that token and cannot be dropped. Unsupported tokens emit `unsupported_reference` with their exact spelling span. Digit-free labels such as `ISS-legacy` are diagnostics, not ignored mentions. Ordinary embedded words such as `NOTFR-001` are not references.
2. Whitespace and ordinary prose/list/Markdown separators delimit mentions: commas, semicolons, colons (except qualification/URI precedence in rule 3), `!`, `?`, parentheses, brackets, braces, angle brackets, quotes, table bars and metadata `=`. Balanced enclosing Markdown backtick, `**`, `*`, `__` or `_` delimiters are syntax, not label content. Only genuinely enclosing delimiters may be removed; never strip internal or unmatched wrapper-like characters to obtain a valid prefix. Preserve code-span delimiter run lengths. Inside a matched inline-code span, a final dot is literal; outside inline code, exactly one trailing full stop is sentence punctuation. Thus `See FR-001.` references `FR-001`, while `` `FR-001.` `` reports the complete unsupported label. Two dots remain interval syntax, not stripped punctuation. This explicitly separates prose spelling from a literal opaque label; it does not rename stored labels.
3. The only implicit local filename shorthand is the exact spec-root-relative shape `investigation/<supported-ID>.md`, with no leading path, normalization, query, fragment or extra suffix. Its reference span remains the ID substring, preserving existing evidence anchors. It is recognized both plain and in inline code. `U-001.md` alone, `other/U-001.md`, `./investigation/U-001.md`, `../investigation/U-001.md`, `/investigation/U-001.md`, `specs/other/investigation/U-001.md`, and `investigation/U-001.md.extra` are not localized by basename. Any ID-bearing path, URI, fragment or `scope::label` outside that exact shorthand emits `unsupported_qualified_reference` over the complete locator. An unsupported label inside the local shape emits a diagnostic and no shorter ID. Do not percent-decode, normalize paths or resolve namespaces. Preserve existing `specs/002-other/spec.md#FR-001` and `002-other::FR-002` full diagnostic spans.

   URI precedence includes a scheme-shaped prefix `[A-Za-z][A-Za-z0-9+.-]*:` followed immediately by non-whitespace content, not only `://` or a scheme allowlist. `urn:FR-001`, `mailto:FR-001@example.org`, ambiguous `Label:FR-001` and `FR-001:FR-002` are complete unsupported qualified locators. Spaced prose `See: FR-001` and `FR-001: FR-002` remains ordinary colon-delimited mentions. Test exact spans and no local leakage for both non-hierarchical schemes and those ambiguity/control pairs.
4. Keep the existing interval separators: en dash, em dash, `..`, and whitespace-surrounded ASCII hyphen. Endpoints must each be complete supported numeric labels, same family and nondecreasing by the existing unbounded decimal helper. Retain a valid interval as one unexpanded reference with exact full span. Unsupported/qualified endpoint, reversed/cross-kind/composite endpoint, missing endpoint, or a chained interval produces a diagnostic for the entire expression with no singleton fallback. Qualified expressions keep `unsupported_qualified_reference`; other invalid intervals use `invalid_range`. `FR-001 - implementation note` remains an ordinary singleton plus prose, not a dangling ASCII-hyphen interval. Test invalid whole endpoints on both sides so neither range nor singleton regex can leak a prefix.

   For en dash, em dash and double-dot separators, an immediately adjacent non-identity atom is an unsupported endpoint even across horizontal whitespace. Do not guess it away as prose: bare `See ..FR-001` includes `See` in the invalid-range diagnostic. An explicit enclosing expression wrapper or ordinary delimiter still bounds the expression; in ``See `..FR-001` `` the preceding `See` remains outside the diagnostic. The ASCII prose-dash exception above remains, but repeated/mixed malformed separator sequences such as `FR-001 - - FR-003` must reject the entire expression without singleton fallback.
5. This scanner is not a namespace resolver, interval expander, historical-source authenticator or semantic assessor. Existing candidate/history consumers continue to block unsupported intervals and qualifications. Supported typed grammar does not adopt opaque labels automatically; explicit historical reconciliation remains outstanding.

**First regression before production edits:**

```python
import pytest
from harness.element_artifacts import parse_identity_artifact

pytestmark = pytest.mark.unit

@pytest.mark.parametrize("label", ["FR-001.other", "FR-001-extra", "ISS-legacy"])
def test_unsupported_whole_reference_cannot_leak_shorter_identity(label):
    text = "Résumé ⚡\r\n" + label + "\r\n"
    parsed = parse_identity_artifact(path="notes.md", role="references", text=text)
    assert parsed.references == ()
    assert len(parsed.diagnostics) == 1
    diagnostic, = parsed.diagnostics
    assert diagnostic.code == "unsupported_reference"
    assert (text[diagnostic.span.start:diagnostic.span.end], diagnostic.span.line) == (label, 2)
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_artifact_reference_tokens.py -q` and retain actual behavior-level RED before introducing the scanner.
- [ ] Implement the single scanner and relation adapter. Use the existing unbounded numeric conversion for interval order; do not call `int` on arbitrary-width decimal strings or expand intervals. Maintain exact Python-string offsets, original source hashes and source-order multiplicity.
- [ ] Add table-driven real-parser tests for all seven families and opaque suffixes (including digit-free, dot, hyphen, underscore, Unicode and internal single/double star/backtick); balanced wrappers, unmatched/internal wrappers, sentence punctuation versus literal final dot; normal supported composites and eight-digit/5000-digit IDs; ordinary embedded words and adjacent independent mentions. Include Unicode/CRLF prefix offsets and inactive-source controls.
- [ ] Cover the full locator contract, including plain/code local investigation paths, opaque local basenames, path traversal, foreign-spec prefix, absolute paths, URIs, query/fragment/extra suffix, qualified opaque labels and qualified interval endpoints. Verify exact spans and no leaked local targets. Include ID-bearing directory names so a path cannot yield several local singleton IDs.
- [ ] Cover whole valid and invalid ranges, both malformed endpoint positions, dangling separators, chains, comma-separated independent intervals, wrappers and metadata `req`/`depends` ownership. Retain existing valid local filename label-only spans and valid range full spans; do not rewrite stored reference anchors or fingerprints.
- [ ] Add a discovery candidate regression using an actual initialized/imported/adopted `U-001` authority and a reference image `U-001.other`: it must report `unsupported_reference`, expose no accepted shorter reference, and retain the exact full SQL dump. Add historical inventory coverage with a valid FR-001 declaration plus `FR-001.other`: the report must contain `artifact_diagnostic` and must not emit a reference to FR-001 for the unsupported token. Keep all reports unassessed and caller-supplied.
- [ ] Run exactly these covering modules with the checkout virtualenv: `test_element_artifact_reference_tokens.py`, `test_element_artifacts.py`, `test_discovery_identity_candidate.py`, `test_definition_identity_candidate.py`, `test_supplemental_identity_bundle.py`, `test_issue_identity_candidate.py`, and `test_element_identity_history.py`, all under `tests/unit/`. No full-repository, capacity or provider run. If a named module path does not exist, report it before substituting a suite.
- [ ] Self-review the lexical precedence and every branch that could leak a shorter prefix. Document the punctuation/literal and exact local shorthand contract, unsupported behavior and inactive rollout status. Run `git diff --check`; commit only the task's files. Report all actual RED/GREEN commands and outputs, fixture corrections, limitations and the commit in the task report; return only the short status contract. Do not repeat an unchanged passing suite solely after committing.

## Subsequent integration

Complete lexical rejection removes a specific bypass; it does not activate managed publication or authenticate historical reconciliation. Qualified-reference resolution and interval application remain explicit unsupported operations until a resolver can bind the correct namespace and revisions. Publication, semantic review, pending-write recovery, graph history and producer/repair integration remain required by the approved design.
