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


def parse(text):
    return parse_identity_artifact(path="notes.md", role="references", text=text)


@pytest.mark.parametrize("family", ["AC", "FR", "NFR", "ISS", "U", "A", "T"])
@pytest.mark.parametrize("suffix", ["legacy", "001.other", "001-extra", "001_extra", "001é", "001*other", "001**other", "001`other", "001``other"])
@pytest.mark.parametrize("wrapper", ["", "`", "**", "*", "__", "_"])
def test_opaque_tokens_keep_whole_spelling_inside_balanced_wrappers(family, suffix, wrapper):
    label = f"{family}-{suffix}"
    text = f"Résumé ⚡\r\nSee {wrapper}{label}{wrapper}\r\n"
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_reference"
    assert (diagnostic.span.start, diagnostic.span.end, diagnostic.span.line) == (14 + len(wrapper), 14 + len(wrapper) + len(label), 2)


@pytest.mark.parametrize("label", ["AC-001a", "FR-001abc", "T-S01", "T-S01a", "NFR-12345678", "ISS-001", "U-001", "A-001", "FR-" + "9" * 5000], ids=["ac-composite", "fr-composite", "task-legacy", "task-legacy-suffix", "wide", "issue", "unknown", "assumption", "unbounded"])
@pytest.mark.parametrize("wrapper", ["", "`", "``", "**", "*", "__", "_"])
def test_supported_complete_labels_preserve_offsets_and_hash(label, wrapper):
    import hashlib

    text = f"Résumé ⚡\r\nSee {wrapper}{label}{wrapper}.\r\n"
    result = parse(text)
    assert not result.diagnostics
    reference, = result.references
    assert (reference.target_id, reference.range_end_id) == (label, None)
    assert (reference.span.start, reference.span.end, reference.span.line) == (14 + len(wrapper), 14 + len(wrapper) + len(label), 2)
    assert result.content_sha256 == hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("source,spelling", [("FR-001*", "FR-001*"), ("FR-001**", "FR-001**"), ("FR-001`", "FR-001`"), ("*FR-001", "*FR-001"), ("_FR-001", "_FR-001"), ("__FR-001", "__FR-001"), ("`FR-001``", "`FR-001``"), ("``FR-001`", "``FR-001`"), ("`FR-001.`", "FR-001."), ("``FR-001.``", "FR-001."), ("``FR-001`other``", "FR-001`other"), ("FR-001.*other*", "FR-001.*other*"), ("FR-001.`other`", "FR-001.`other`")])
def test_unmatched_wrappers_and_literal_final_dots_are_not_trimmed(source, spelling):
    result = parse("See " + source)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_reference"
    assert ("See " + source)[diagnostic.span.start:diagnostic.span.end] == spelling


def test_separators_multiplicity_and_embedded_words():
    text = 'NOTFR-001 éFR-001 FR-001,FR-002;FR-003: FR-004!FR-005? (FR-006)[FR-007]{FR-008}<FR-009>"FR-010"|FR-011|req=FR-012 FR-001.'
    result = parse(text)
    assert not result.diagnostics
    assert [r.target_id for r in result.references] == [f"FR-{i:03}" for i in range(1, 13)] + ["FR-001"]


@pytest.mark.parametrize("source", ["investigation/U-001.md", "`investigation/U-001.md`", "``investigation/AC-001a.md``"])
def test_exact_investigation_shorthand_retains_label_only_anchor(source):
    result = parse(source)
    assert not result.diagnostics
    reference, = result.references
    label = "AC-001a" if "AC-" in source else "U-001"
    assert reference.target_id == label
    assert (reference.span.start, reference.span.end) == (source.index(label), source.index(label) + len(label))


@pytest.mark.parametrize("locator", ["U-001.md", "other/U-001.md", "./investigation/U-001.md", "../investigation/U-001.md", "/investigation/U-001.md", "specs/other/investigation/U-001.md", "investigation/U-001.md.extra", "investigation/U-001.md?q=1", "investigation/U-001.md#note", "specs/002-other/spec.md#FR-001", "002-other::FR-002", "scope::FR-001.other", "https://example.org/FR-001?q=U-002#A-001", "#FR-001", "U-001/FR-002/A-003.md", "investigation/U-001.other.md", "investigation/ISS-legacy.md"])
@pytest.mark.parametrize("wrapper", ["", "`"])
def test_locators_cannot_localize_any_basename_or_directory(locator, wrapper):
    text = f"See {wrapper}{locator}{wrapper}."
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_qualified_reference"
    assert text[diagnostic.span.start:diagnostic.span.end] == locator


@pytest.mark.parametrize("locator", ["urn:FR-001", "urn:example:FR-001", "https://example.org:8080/FR-001", "mailto:FR-001@example.org", "custom+v1:FR-001.other", "Label:FR-001", "FR-001:FR-002"])
@pytest.mark.parametrize("wrapper", ["", "`"])
def test_uri_scheme_shapes_are_rejected_without_scheme_guessing(locator, wrapper):
    text = f"See {wrapper}{locator}{wrapper}."
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_qualified_reference"
    assert text[diagnostic.span.start:diagnostic.span.end] == locator


def test_spaced_colons_delimit_ordinary_prose_mentions():
    result = parse("See: FR-001: FR-002")
    assert not result.diagnostics
    assert [r.target_id for r in result.references] == ["FR-001", "FR-002"]


@pytest.mark.parametrize("locator", ["scope::`FR-001`", "scope::**FR-001**", "scope::__FR-001__", "urn:`FR-001`", "urn:**FR-001**", "urn:_FR-001_", "FR-001:`other`"])
def test_internal_locator_wrappers_cannot_detach_a_local_id(locator):
    result = parse("See " + locator)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_qualified_reference"
    assert ("See " + locator)[diagnostic.span.start:diagnostic.span.end] == locator


@pytest.mark.parametrize("prefix", ["https://example.org?", "https://example.org?q=", "other/file.md?", "other/file.md?q=", "scope::value?key="])
@pytest.mark.parametrize("wrapper", ["`", "``", "**", "*", "__", "_"])
def test_query_position_wrappers_remain_part_of_the_complete_locator(prefix, wrapper):
    locator = f"{prefix}{wrapper}FR-001{wrapper}"
    text = f"Résumé ⚡\r\nSee {locator}."
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_qualified_reference"
    assert (text[diagnostic.span.start:diagnostic.span.end], diagnostic.span.line) == (locator, 2)


def test_metadata_assignment_wrappers_still_enclose_independent_references():
    result = parse("req=`FR-001` depends=**T-002**")
    assert not result.diagnostics
    assert [r.target_id for r in result.references] == ["FR-001", "T-002"]


@pytest.mark.parametrize("source", ["` FR-001. `", "`` FR-001. ``", "`prose FR-001. more prose`"])
def test_code_span_whitespace_does_not_make_literal_dot_prose_punctuation(source):
    result = parse("See " + source)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_reference"
    assert ("See " + source)[diagnostic.span.start:diagnostic.span.end] == "FR-001."


def test_nested_enclosing_wrappers_preserve_label_and_literal_context():
    text = "See **`FR-001`** and __*FR-002*__."
    result = parse(text)
    assert not result.diagnostics
    assert [r.target_id for r in result.references] == ["FR-001", "FR-002"]


@pytest.mark.parametrize("expression", ["FR-001..FR-003", "FR-001–FR-003", "FR-001—FR-003", "FR-001 - FR-003", "FR-1..FR-" + "9" * 5000], ids=["dots", "en", "em", "ascii", "unbounded"])
@pytest.mark.parametrize("wrapper", ["", "`", "**"])
def test_valid_ranges_are_whole_unexpanded_expressions(expression, wrapper):
    text = f"See {wrapper}{expression}{wrapper}."
    result = parse(text)
    assert not result.diagnostics
    reference, = result.references
    assert reference.range_end_id == ("FR-" + "9" * 5000 if expression.startswith("FR-1..") else "FR-003")
    assert text[reference.span.start:reference.span.end] == expression


@pytest.mark.parametrize("expression", ["FR-001.other..FR-003", "FR-001..FR-003.other", "FR-001-extra–FR-003", "FR-001–FR-003-extra", "ISS-legacy..ISS-003", "ISS-001..ISS-legacy", "FR-003..FR-001", "FR-001..AC-003", "FR-001a..FR-003", "FR-001..FR-003a", "FR-001..", "..FR-001", "FR-001–", "–FR-001", "FR-001..FR-002..FR-003", "FR-001..FR-002..", "FR-001..unsupported", "unsupported..FR-001"])
@pytest.mark.parametrize("wrapper", ["", "`", "**"])
def test_invalid_intervals_never_leak_either_endpoint(expression, wrapper):
    text = f"See {wrapper}{expression}{wrapper}, next."
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "invalid_range"
    expected = "See " + expression if not wrapper and expression.startswith(("..", "–")) else expression
    assert text[diagnostic.span.start:diagnostic.span.end] == expected


@pytest.mark.parametrize("expression", ["scope::FR-001..FR-003", "FR-001..scope::FR-003", "other/FR-001.md–FR-003", "FR-001–other/FR-003.md", "investigation/FR-001.md..FR-003", "FR-001..investigation/FR-003.md", "scope::FR-001.other..FR-003"])
def test_qualified_interval_rejection_has_precedence(expression):
    result = parse(expression)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_qualified_reference"
    assert expression[diagnostic.span.start:diagnostic.span.end] == expression


def test_independent_intervals_wrapped_endpoints_and_prose_dash():
    text = "`FR-001`..`FR-002`, **FR-003** – **FR-004**; FR-005 - implementation note"
    result = parse(text)
    assert not result.diagnostics
    assert [(r.target_id, r.range_end_id) for r in result.references] == [("FR-001", "FR-002"), ("FR-003", "FR-004"), ("FR-005", None)]
    assert [text[r.span.start:r.span.end] for r in result.references] == ["FR-001`..`FR-002", "FR-003** – **FR-004", "FR-005"]


def test_inactive_sources_and_exclusions_cannot_join_or_leak_tokens():
    text = "---\nref: FR-001.other\n---\n```\nFR-001.other\n```\n    FR-001.other\n> FR-001.other\n<!-- FR-001.other -->\nFR-001<!-- hidden -->.other\nVisible `FR-002`.\n"
    result = parse(text)
    assert [r.target_id for r in result.references] == ["FR-002"]
    assert not result.diagnostics


@pytest.mark.parametrize("text", ["See `FR-001\n<!-- ` -->", "See **FR-001\n<!-- ** -->"])
def test_inactive_wrapper_closer_cannot_complete_a_visible_token(text):
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "unsupported_reference"


def test_active_mentions_after_inactive_blocks_keep_their_boundaries():
    text = "---\nname: Example\n---\nFR-001\n```\nFR-002.other\n```\nFR-003\n"
    result = parse(text)
    assert not result.diagnostics
    assert [r.target_id for r in result.references] == ["FR-001", "FR-003"]


@pytest.mark.parametrize("expression", ["FR-001...", "FR-001....FR-003", "FR-001..–FR-003", "FR-001..FR-002 - FR-003", "FR-001 - FR-002 - FR-003"])
def test_chained_or_repeated_separators_have_one_complete_diagnostic(expression):
    result = parse(expression)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "invalid_range"
    assert expression[diagnostic.span.start:diagnostic.span.end] == expression


def test_ascii_interval_without_right_endpoint_is_diagnostic():
    text = "See FR-001 - \n"
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "invalid_range"
    assert text[diagnostic.span.start:diagnostic.span.end] == "FR-001 -"


@pytest.mark.parametrize("expression", ["FR-001 - - FR-003", "FR-001 - - - FR-003", "FR-001 - – FR-003", "FR-001 – - FR-003", "FR-001 - -", "FR-001 - - unsupported", "FR-001 - - scope::FR-003"])
def test_repeated_ascii_separators_cannot_return_singleton_endpoints(expression):
    result = parse(expression)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == ("unsupported_qualified_reference" if "scope::" in expression else "invalid_range")
    assert expression[diagnostic.span.start:diagnostic.span.end] == expression


@pytest.mark.parametrize("separator", ["–", "—", ".."])
@pytest.mark.parametrize("expression", ["FR-001 {sep} unsupported", "unsupported {sep} FR-001", "See {sep}FR-001"])
def test_spaced_unsupported_interval_endpoint_is_retained_in_full(separator, expression):
    text = expression.format(sep=separator)
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "invalid_range"
    assert text[diagnostic.span.start:diagnostic.span.end] == text


@pytest.mark.parametrize("wrapper", ["`", "**", "__"])
@pytest.mark.parametrize("expression", ["..FR-001", "FR-001.."])
def test_enclosing_interval_wrapper_separates_adjacent_prose(wrapper, expression):
    text = f"See {wrapper}{expression}{wrapper} afterwards"
    result = parse(text)
    assert not result.references
    diagnostic, = result.diagnostics
    assert diagnostic.code == "invalid_range"
    assert text[diagnostic.span.start:diagnostic.span.end] == expression


def test_scanner_is_pure_and_does_not_extract_excluded_prefixes():
    from harness.element_artifact_reference_tokens import scan_reference_tokens

    text = "FR-001.other, FR-002"
    active = bytearray(b"\1" * len(text))
    excluded = [(6, 12)]
    before = active[:]
    tokens = scan_reference_tokens(text, active=active, excluded_spans=excluded)
    assert active == before and excluded == [(6, 12)]
    assert [(t.start, t.end, t.target_id) for t in tokens] == [(14, 20, "FR-002")]


def test_task_metadata_range_relations_and_nested_owner_survive():
    text = "- [ ] T-001 complexity=standard phase=core req=FR-001..FR-003 depends=T-002..T-003\n  **Title:** Task.\n  Detail FR-004.\n"
    result = parse_identity_artifact(path="tasks.md", role="tasks", text=text)
    assert not result.diagnostics
    assert [(r.target_id, r.range_end_id, r.relation, r.owner_id) for r in result.references] == [("FR-001", "FR-003", "requires", "T-001"), ("T-002", "T-003", "depends", "T-001"), ("FR-004", None, "reference", "T-001")]
