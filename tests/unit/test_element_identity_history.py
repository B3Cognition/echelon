"""Read-only inventory of explicitly supplied historical artifact images."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


def artifact(path="spec.md", role="requirements", text="- **FR-001**: Move.\n"):
    return {"path": path, "role": role, "text": text}


def request_for(*images):
    return {"schema_version": 1, "spec_id": "demo", "snapshots": [
        {"snapshot_id": str(i), "artifacts": list(imageset)} for i, imageset in enumerate(images)]}


def inventory(request):
    from harness.element_identity_history import inventory_history
    return inventory_history(request)


def conflicts(result, code):
    return [c for c in result["conflicts"] if c["code"] == code]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_opaque_reference_cannot_resolve_to_valid_historical_declaration():
    text = "- FR-001: Move.\r\nRésumé ⚡\r\nFR-001.other\r\n"
    request = request_for([artifact(text=text)])
    before = deepcopy(request)
    result = inventory(request)
    assert request == before
    assert (result["assessment"], result["source_authentication"]) == ("unassessed", "caller_supplied")
    row, = result["snapshots"][0]["artifacts"]
    assert row["declarations"][0]["element_id"] == "FR-001"
    assert row["references"] == []
    assert row["content_sha256"] == sha(text)
    diagnostic, = row["diagnostics"]
    assert diagnostic["code"] == "unsupported_reference"
    span = diagnostic["span"]
    assert (text[span["start"]:span["end"]], span["line"]) == ("FR-001.other", 3)
    conflict, = result["conflicts"]
    assert conflict["code"] == "artifact_diagnostic"
    assert "unsupported_reference" in conflict["detail"]


def test_removed_question_keeps_evidence_unassessed_and_unresolved():
    from harness.element_identity_history import inventory_history
    request = {"schema_version": 1, "spec_id": "demo", "snapshots": [
        {"snapshot_id": "before", "artifacts": [
            {"path": "unknowns.md", "role": "unknowns", "text": "### U-005: Collision\nInvestigate.\n"},
            {"path": "evidence.md", "role": "evidence", "text": "U-005 needs evidence.\n"}]},
        {"snapshot_id": "after", "artifacts": [
            {"path": "unknowns.md", "role": "unknowns", "text": ""},
            {"path": "evidence.md", "role": "evidence", "text": "U-005 needs evidence.\n"}]},
    ]}
    result = inventory_history(request)
    assert result["assessment"] == "unassessed"
    assert {c["code"] for c in result["conflicts"]} == {"definition_missing", "unresolved_reference"}
    after_evidence = next(a for a in result["snapshots"][1]["artifacts"] if a["path"] == "evidence.md")
    assert after_evidence["references"][0]["target_id"] == "U-005"
    assert after_evidence["references"][0]["assessment"] == "unassessed"


def test_clean_report_is_detached_unassessed_and_digest_is_canonical():
    source = request_for([artifact("z.md"), artifact("a.md", "evidence", "FR-001.\r\n")])
    before = deepcopy(source)
    result = inventory(source)
    assert source == before
    assert set(result) == {"report_version", "spec_id", "input_sha256", "coverage", "source_authentication", "assessment", "snapshots", "conflicts"}
    assert (result["coverage"], result["source_authentication"], result["assessment"]) == ("declared_snapshots_only", "caller_supplied", "unassessed")
    assert result["conflicts"] == []
    canonical = deepcopy(source)
    canonical["snapshots"][0]["artifacts"].reverse()
    assert result == inventory(canonical)
    assert result["input_sha256"] == sha(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    row = result["snapshots"][0]["artifacts"][1]
    assert row["content_sha256"] == sha(source["snapshots"][0]["artifacts"][0]["text"])
    assert set(row) == {"path", "role", "present", "content_sha256", "declarations", "references", "diagnostics"}
    assert set(row["declarations"][0]) == {"element_id", "kind", "disposition", "caption", "span", "label_span", "content_sha256"}
    result["snapshots"][0]["artifacts"][1]["declarations"][0]["span"]["start"] = 999
    source["snapshots"][0]["artifacts"][0]["text"] = "mutated"
    assert inventory(before)["snapshots"][0]["artifacts"][1]["declarations"][0]["span"]["start"] == 0


def test_sanitized_discovery_history_retains_exact_hashes_spans_and_evidence():
    fixture = Path("tests/fixtures/element_identity/discovery")
    evidence = (fixture / "evidence-grades.md").read_text()
    source = request_for(*[[artifact("unknowns.md", "unknowns", (fixture / image / "unknowns.md").read_text()), artifact("evidence.md", "evidence", evidence)] for image in ("before", "after")])
    result = inventory(source)
    assert [c["element_ids"] for c in conflicts(result, "definition_changed")] == [[f"U-00{i}"] for i in range(1, 5)]
    assert [c["element_ids"] for c in conflicts(result, "definition_missing")] == [["U-005"]]
    assert [c["element_ids"] for c in conflicts(result, "unresolved_reference")] == [["U-005"]]
    for snapshot, supplied in zip(result["snapshots"], source["snapshots"]):
        for row in snapshot["artifacts"]:
            text = next(a["text"] for a in supplied["artifacts"] if a["path"] == row["path"])
            assert row["content_sha256"] == sha(text)
            for declaration in row["declarations"]:
                span = declaration["span"]
                assert declaration["content_sha256"] == sha(text[span["start"]:span["end"]])
            assert all(r["assessment"] == "unassessed" for r in row["references"])
    missing = conflicts(result, "definition_missing")[0]
    assert missing["locations"][-1] == {"snapshot_id": "1", "path": "unknowns.md", "artifact_sha256": sha(source["snapshots"][1]["artifacts"][0]["text"]), "span": None}


def test_introduction_move_and_removal_are_distinct():
    definition = "- FR-001: Move.\n"
    result = inventory(request_for([artifact("a.md", text=None), artifact("b.md", text="")], [artifact("a.md", text=definition), artifact("b.md", text="")], [artifact("a.md", text=None), artifact("b.md", text=definition)], [artifact("a.md", text=None), artifact("b.md", text=None)]))
    assert {c["code"] for c in result["conflicts"]} == {"definition_missing"}
    assert [loc["snapshot_id"] for loc in result["conflicts"][0]["locations"]] == ["2", "3"]
    assert result["conflicts"][0]["locations"][-1]["artifact_sha256"] is None


@pytest.mark.parametrize("digits", ["1000000", "1" + "0" * 4301], ids=["seven-digits", "over-4300-digits"])
def test_padding_aliases_across_history_do_not_normalize_or_convert_whole_numbers(digits):
    first, second = "FR-" + digits, "FR-0" + digits
    result = inventory(request_for([artifact(text=f"- {first}: Move.\n")], [artifact(text=f"- {second}: Move.\n{second} needs evidence.\n")]))
    assert set(conflicts(result, "padding_alias")[0]["element_ids"]) == {first, second}
    assert conflicts(result, "ambiguous_reference")[0]["element_ids"] == [second]


def test_duplicate_and_content_variants_keep_all_locations():
    result = inventory(request_for([artifact("a.md"), artifact("b.md")], [artifact("a.md", text="- FR-001: Changed.\n"), artifact("b.md", text="")]))
    assert len(conflicts(result, "duplicate_definition")[0]["locations"]) == 2
    assert len(conflicts(result, "definition_changed")[0]["locations"]) == 3
    assert not conflicts(result, "definition_missing")


def test_reference_resolution_is_snapshot_local_and_ranges_are_not_expanded():
    result = inventory(request_for([artifact(text="- FR-001: One.\n- FR-001: Two.\nFR-001 FR-002 FR-003..FR-005 other::FR-006\n")]))
    assert [c["element_ids"] for c in conflicts(result, "ambiguous_reference")] == [["FR-001"]]
    assert [c["element_ids"] for c in conflicts(result, "unresolved_reference")] == [["FR-002"]]
    assert conflicts(result, "unsupported_reference_range")[0]["element_ids"] == ["FR-003", "FR-005"]
    assert any("unsupported_qualified_reference" in c["detail"] for c in conflicts(result, "artifact_diagnostic"))


@pytest.mark.parametrize("second_body", ["Body\r\n", "Other body\r\n"])
def test_issue_occurrences_retain_typed_fingerprints_and_require_mapping(second_body):
    from harness.issue_identity import issue_fingerprint
    first = "### ISS-001: Collision ⚡\r\nBody\r\n### Resolution Guidance\r\nFix.\r\n### Notes\r\nFooter.\r\n"
    second = "### ISS-001: Collision ⚡\r\n" + second_body + "### Resolution Guidance\r\nFix.\r\n### Notes\r\nFooter.\r\n"
    result = inventory(request_for([artifact("issues.md", "issues", first)], [artifact("issues.md", "issues", second)]))
    mapping = conflicts(result, "issue_mapping_required")[0]
    assert len(mapping["locations"]) == 2
    assert {c["code"] for c in result["conflicts"]} == {"issue_mapping_required"}
    for i, text in enumerate((first, second)):
        declaration = result["snapshots"][i]["artifacts"][0]["declarations"][0]
        body = text.split("\n", 1)[1].split("### Notes", 1)[0]
        assert declaration["typed_fingerprint"] == issue_fingerprint("Collision ⚡", body)
        assert declaration["content_sha256"] == sha(text.split("### Notes", 1)[0])
        assert declaration["disposition"] == "occurrence"


def test_issue_reference_never_resolves_by_display_label_even_without_occurrence():
    result = inventory(request_for([artifact("evidence.md", "evidence", "ISS-001 needs mapping.\n")]))
    assert [c["code"] for c in result["conflicts"]] == ["issue_mapping_required"]


@pytest.mark.parametrize("first", ["ISS-001", "ISS-000"])
def test_issue_range_retains_interval_and_maps_only_valid_explicit_endpoints(first):
    text = f"{first}..ISS-003\n"
    result = inventory(request_for([artifact("evidence.md", "evidence", text)]))
    mappings = conflicts(result, "issue_mapping_required")
    assert [c["element_ids"] for c in mappings] == (
        [["ISS-001"], ["ISS-003"]] if first == "ISS-001" else [["ISS-003"]]
    )
    assert [c["element_ids"] for c in conflicts(result, "unsupported_reference_range")] == [[first, "ISS-003"]]
    assert bool(conflicts(result, "invalid_identity_label")) is (first == "ISS-000")
    assert not conflicts(result, "unresolved_reference")
    row = result["snapshots"][0]["artifacts"][0]
    assert len(row["references"]) == 1
    assert (row["references"][0]["target_id"], row["references"][0]["range_end_id"]) == (first, "ISS-003")
    for mapping in mappings:
        assert mapping["locations"] == [{"snapshot_id": "0", "path": "evidence.md", "artifact_sha256": sha(text), "span": {"start": 0, "end": 16, "line": 1}}]


@pytest.mark.parametrize("role,text", [("references", "- FR-001: Move.\n"), ("references", "different"), ("requirements", "different")])
def test_one_physical_path_cannot_supply_multiple_roles_or_images(role, text):
    from harness.element_identity_history import HistoryInventoryError
    with pytest.raises(HistoryInventoryError, match="artifact paths must be unique"):
        inventory(request_for([artifact(), artifact(role=role, text=text)]))


def test_invalid_zero_labels_are_facts_but_not_resolvable_authority():
    result = inventory(request_for([artifact(text="- FR-000: Zero.\nFR-000 FR-001\n")]))
    assert len(conflicts(result, "invalid_identity_label")) == 2
    assert [c["element_ids"] for c in conflicts(result, "unresolved_reference")] == [["FR-001"]]
    assert result["snapshots"][0]["artifacts"][0]["declarations"][0]["element_id"] == "FR-000"


def test_opaque_declarations_remain_diagnostics_not_invented_allocations():
    result = inventory(request_for([artifact(text="- FR-legacy: One.\n- FR-other: Two.\n")]))
    assert len(conflicts(result, "artifact_diagnostic")) == 2
    assert not result["snapshots"][0]["artifacts"][0]["declarations"]


def test_quoted_and_fenced_mentions_do_not_create_conflicts():
    result = inventory(request_for([artifact(text="> ### FR-legacy: Quote\n~~~\n- FR-001: Example\n~~~\n")]))
    assert result["conflicts"] == []


@pytest.mark.parametrize("text", [None, "", "invalid"])
def test_absent_lexicon_skips_grammar_but_empty_or_malformed_present_does_not(text):
    result = inventory(request_for([artifact("native.lex", "lexicon", text)]))
    row = result["snapshots"][0]["artifacts"][0]
    assert row["present"] is (text is not None)
    assert row["content_sha256"] == (None if text is None else sha(text))
    assert bool(conflicts(result, "artifact_diagnostic")) is (text is not None)


def test_projection_is_not_authority():
    text = "ARTIFACT: SPEC\nTITLE: Game\n\nREQ: FR-001\nGIVEN: an active player\nWHEN: movement is requested\nTHEN: the game MUST move the player\n"
    result = inventory(request_for([artifact("native.lex", "lexicon_projection", text), artifact("evidence.md", "evidence", "FR-001\n")]))
    assert result["snapshots"][0]["artifacts"][1]["declarations"][0]["disposition"] == "projection"
    assert [c["element_ids"] for c in conflicts(result, "unresolved_reference")] == [["FR-001"]]


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(extra=1), lambda r: r.update(schema_version=True),
    lambda r: r.update(schema_version=2), lambda r: r.update(spec_id=" "),
    lambda r: r.update(spec_id="\ud800"), lambda r: r.update(spec_id="x\x00"),
    lambda r: r.update(snapshots=[]), lambda r: r.update(snapshots=()),
    lambda r: r["snapshots"].append(deepcopy(r["snapshots"][0])),
    lambda r: r["snapshots"][0].update(snapshot_id=""),
    lambda r: r["snapshots"][0].update(snapshot_id=True),
    lambda r: r["snapshots"][0].update(extra=1),
    lambda r: r["snapshots"][0].update(artifacts=[]),
    lambda r: r["snapshots"][0]["artifacts"].append(artifact()),
    lambda r: r["snapshots"][0]["artifacts"][0].update(path="../spec.md"),
    lambda r: r["snapshots"][0]["artifacts"][0].update(path="\ud800"),
    lambda r: r["snapshots"][0]["artifacts"][0].update(role="glossary"),
    lambda r: r["snapshots"][0]["artifacts"][0].update(role=False),
    lambda r: r["snapshots"][0]["artifacts"][0].update(text=False),
    lambda r: r["snapshots"][0]["artifacts"][0].update(text="\ud800"),
    lambda r: r["snapshots"][0]["artifacts"][0].update(text="\x00"),
    lambda r: r["snapshots"][0]["artifacts"][0].update(extra=1),
    lambda r: r["snapshots"].append({"snapshot_id": "later", "artifacts": [artifact("other.md")]}),
    lambda r: r["snapshots"].append({"snapshot_id": "later", "artifacts": [artifact(role="evidence")]}),
])
def test_strict_input_validation(mutate):
    from harness.element_identity_history import HistoryInventoryError
    source = request_for([artifact()])
    mutate(source)
    with pytest.raises(HistoryInventoryError):
        inventory(source)


@pytest.mark.parametrize("source", [None, [], True, {"schema_version": 1}])
def test_invalid_top_level(source):
    from harness.element_identity_history import HistoryInventoryError
    with pytest.raises(HistoryInventoryError):
        inventory(source)


def run_command(cwd, *args):
    return subprocess.run([sys.executable, "-m", "harness.element_identity_admin", "inventory-history", *map(str, args)], cwd=cwd, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}, capture_output=True, text=True)


@pytest.mark.parametrize("initialized", [False, True])
@pytest.mark.parametrize("text", ["- FR-001: Move.\n", "### ISS-legacy: Conflict\n"])
def test_command_is_input_only_and_preserves_all_bytes(tmp_path, initialized, text):
    if initialized:
        from harness.element_identity_store import IdentityStore
        IdentityStore.initialize(tmp_path)
    source = request_for([artifact(text=text)])
    path = tmp_path / "input.json"
    path.write_text(json.dumps(source))
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = run_command(tmp_path, "--input", path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == inventory(source)
    assert result.stderr == ""
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert (tmp_path / ".echelon").exists() is initialized


@pytest.mark.parametrize("payload", [b'{', b'\xff', b'{"schema_version":1,"schema_version":1}', b'null', b'{"spec_id":"\\ud800"}', ('{"schema_version":' + '9' * 5000 + '}').encode()], ids=["json", "utf8", "duplicate-key", "type", "unicode-shape", "decoder-limit"])
def test_command_bad_json_and_decoder_limit_are_concise_input_errors(tmp_path, payload):
    path = tmp_path / "input.json"
    path.write_bytes(payload)
    result = run_command(tmp_path, "--input", path)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error:")
    assert "Traceback" not in result.stderr
    assert path.read_bytes() == payload
    assert not (tmp_path / ".echelon").exists()


def test_command_requires_input_and_rejects_workspace(tmp_path):
    for args in [(), ("--workspace", tmp_path)]:
        result = run_command(tmp_path, *args)
        assert result.returncode == 2 and not result.stdout


@pytest.mark.parametrize("field", ["spec_id", "snapshot_id", "path", "text"])
def test_command_rejects_unencodable_scalars_in_valid_shapes(tmp_path, field):
    source = request_for([artifact()])
    if field == "spec_id":
        source[field] = "\ud800"
    elif field == "snapshot_id":
        source["snapshots"][0][field] = "\ud800"
    else:
        source["snapshots"][0]["artifacts"][0][field] = "\ud800"
    path = tmp_path / "input.json"
    payload = json.dumps(source).encode()
    path.write_bytes(payload)
    result = run_command(tmp_path, "--input", path)
    assert result.returncode == 2 and result.stdout == ""
    assert "Traceback" not in result.stderr
    assert path.read_bytes() == payload


def test_native_lexicon_can_define_authority_and_diagnostics_are_exact():
    from harness.element_artifacts import parse_identity_artifact
    text = "ARTIFACT: SPEC\nTITLE: Game\n\nREQ: FR-001\nGIVEN: an active player\nWHEN: movement is requested\nTHEN: the game MUST move the player\n"
    result = inventory(request_for([artifact("native.lex", "lexicon", text), artifact("evidence.md", "evidence", "FR-001\n")]))
    assert result["conflicts"] == []
    malformed = artifact(text="### FR-001.malformed: Caption\r\n")
    result = inventory(request_for([malformed]))
    parsed = parse_identity_artifact(**malformed)
    diagnostic = result["snapshots"][0]["artifacts"][0]["diagnostics"][0]
    assert diagnostic == {"code": parsed.diagnostics[0].code, "span": {"start": 4, "end": 20, "line": 1}, "detail": parsed.diagnostics[0].detail}
    assert result["conflicts"][0]["locations"] == [{"snapshot_id": "0", "path": "spec.md", "artifact_sha256": sha(malformed["text"]), "span": diagnostic["span"]}]
    result["conflicts"][0]["locations"][0]["span"]["start"] = 999
    assert diagnostic["span"]["start"] == 4


def test_repeated_issue_occurrences_within_one_source_remain_separate():
    text = "### ISS-001: Collision\nBody\n### ISS-001: Collision\nBody\n"
    result = inventory(request_for([artifact("issues.md", "issues", text)]))
    declarations = result["snapshots"][0]["artifacts"][0]["declarations"]
    assert len(declarations) == 2
    assert declarations[0]["typed_fingerprint"] == declarations[1]["typed_fingerprint"]
    assert declarations[0]["span"] != declarations[1]["span"]
    assert len(conflicts(result, "issue_mapping_required")[0]["locations"]) == 2
    assert not conflicts(result, "duplicate_definition")


def test_snapshot_order_is_declared_order_and_affects_digest():
    source = request_for([artifact(text="")], [artifact()])
    forward = inventory(source)
    source["snapshots"].reverse()
    reverse = inventory(source)
    assert forward["input_sha256"] != reverse["input_sha256"]
    assert not forward["conflicts"]
    assert [s["snapshot_id"] for s in reverse["snapshots"]] == ["1", "0"]
    assert [c["code"] for c in reverse["conflicts"]] == ["definition_missing"]


def test_programming_errors_are_not_translated_into_input_errors(monkeypatch):
    from harness import element_identity_history
    def broken_parser(**kwargs):
        raise ValueError("unexpected parser bug")
    monkeypatch.setattr(element_identity_history, "parse_identity_artifact", broken_parser)
    with pytest.raises(ValueError, match="unexpected parser bug") as caught:
        inventory(request_for([artifact()]))
    assert type(caught.value) is ValueError


def test_adapter_accepted_whitespace_path_is_not_reinterpreted():
    from harness.element_artifacts import parse_identity_artifact
    image = artifact(" ")
    assert parse_identity_artifact(**image).path == " "
    assert inventory(request_for([image]))["snapshots"][0]["artifacts"][0]["path"] == " "


@pytest.mark.parametrize("role", ["unknowns", "assumptions", "requirements", "tasks", "issues", "lexicon", "lexicon_projection", "investigation", "evidence", "references"])
def test_all_adapter_roles_accept_explicit_absence(role):
    result = inventory(request_for([artifact(role=role, text=None)]))
    assert result["conflicts"] == []
    assert result["snapshots"][0]["artifacts"][0]["role"] == role


def test_supported_opaque_composites_are_distinct_exact_identities():
    result = inventory(request_for([artifact(text="- FR-001legacy: One.\n- FR-000001legacy: Two.\nFR-001legacy FR-000001legacy\n")]))
    assert result["conflicts"] == []
    assert [d["element_id"] for d in result["snapshots"][0]["artifacts"][0]["declarations"]] == ["FR-001legacy", "FR-000001legacy"]


def test_command_does_not_discover_damaged_authority_or_artifact_paths(tmp_path):
    authority = tmp_path / ".echelon" / "identity"
    authority.mkdir(parents=True)
    marker = authority / "authority.json"
    marker.write_bytes(b"deliberately not an authority")
    (tmp_path / "spec.md").write_bytes(b"unrelated current source")
    path = tmp_path / "input.json"
    path.write_text(json.dumps(request_for([artifact()])))
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = run_command(tmp_path, "--input", path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["conflicts"] == []
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
