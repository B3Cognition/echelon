"""Pure, unassessed inventory of caller-supplied historical artifact images."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

from kernel.element_ids import decimal_to_int, element_id_sort_key
from harness.element_artifacts import _validate_input, parse_identity_artifact
from harness.element_identity_lifecycle import label as validate_label
from harness.issue_identity import issue_fingerprint


class HistoryInventoryError(ValueError):
    """Malformed explicitly supplied historical inventory input."""


def _object(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise HistoryInventoryError(f"{name} has invalid object keys")


def _string(value, name, *, nonblank=True):
    if type(value) is not str or (nonblank and not value.strip()) or "\x00" in value:
        raise HistoryInventoryError(f"{name} must be a {'nonblank ' if nonblank else ''}string without NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise HistoryInventoryError(f"{name} must be UTF-8 encodable") from error


def _array(value, name):
    if type(value) is not list or not value:
        raise HistoryInventoryError(f"{name} must be a nonempty array")


def _validated_request(request):
    _object(request, ("schema_version", "spec_id", "snapshots"), "request")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise HistoryInventoryError("schema_version must be integer 1")
    _string(request["spec_id"], "spec_id")
    _array(request["snapshots"], "snapshots")
    snapshots, seen, captured = [], set(), None
    for snapshot in request["snapshots"]:
        _object(snapshot, ("snapshot_id", "artifacts"), "snapshot")
        _string(snapshot["snapshot_id"], "snapshot_id")
        if snapshot["snapshot_id"] in seen:
            raise HistoryInventoryError("snapshot IDs must be unique")
        seen.add(snapshot["snapshot_id"])
        _array(snapshot["artifacts"], "artifacts")
        artifacts, paths = [], set()
        for artifact in snapshot["artifacts"]:
            _object(artifact, ("path", "role", "text"), "artifact")
            _string(artifact["path"], "path", nonblank=False)
            if artifact["text"] is not None:
                _string(artifact["text"], "text", nonblank=False)
            try:
                _validate_input(path=artifact["path"], role=artifact["role"], text="")
            except ValueError as error:
                raise HistoryInventoryError(str(error)) from error
            if artifact["path"] in paths:
                raise HistoryInventoryError("artifact paths must be unique within each snapshot")
            paths.add(artifact["path"])
            artifacts.append(dict(artifact))
        path_roles = {(a["path"], a["role"]) for a in artifacts}
        if captured is not None and path_roles != captured:
            raise HistoryInventoryError("snapshots must capture the same path/role set")
        captured = path_roles
        snapshots.append({"snapshot_id": snapshot["snapshot_id"],
                          "artifacts": sorted(artifacts, key=lambda a: a["path"])})
    return {"schema_version": 1, "spec_id": request["spec_id"], "snapshots": snapshots}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _artifact_report(artifact):
    row = {"path": artifact["path"], "role": artifact["role"],
           "present": artifact["text"] is not None, "content_sha256": None,
           "declarations": [], "references": [], "diagnostics": []}
    if not row["present"]:
        return row
    parsed = parse_identity_artifact(**artifact)
    row["content_sha256"] = parsed.content_sha256
    for declaration in parsed.declarations:
        item = asdict(declaration)
        item["content_sha256"] = _sha(item.pop("content"))
        if declaration.disposition == "occurrence" and declaration.kind == "ISS":
            body = declaration.content.partition("\n")[2]
            item["typed_fingerprint"] = issue_fingerprint(declaration.caption, body)
        row["declarations"].append(item)
    row["references"] = [{**asdict(ref), "assessment": "unassessed"} for ref in parsed.references]
    row["diagnostics"] = [asdict(diagnostic) for diagnostic in parsed.diagnostics]
    return row


def _location(snapshot, artifact, span):
    return {"snapshot_id": snapshot["snapshot_id"], "path": artifact["path"],
            "artifact_sha256": artifact["content_sha256"], "span": span}


def _conflict(conflicts, code, ids, locations, detail):
    # Each conflict owns its nested data; projections and other conflicts cannot
    # be changed through a shared span/location returned to a caller.
    unique = {_json(location): location for location in locations}
    conflicts.append({"code": code, "element_ids": sorted(set(ids), key=element_id_sort_key),
                      "locations": deepcopy(list(unique.values())), "detail": detail})


def _eligible(element_id, location, conflicts):
    try:
        validate_label(element_id)
    except ValueError as error:
        _conflict(conflicts, "invalid_identity_label", [element_id], [location], str(error))
        return False
    return True


def _collect(snapshots, conflicts):
    definitions, history, issues, references = [], defaultdict(list), defaultdict(list), []
    for snapshot in snapshots:
        local = defaultdict(list)
        for artifact in snapshot["artifacts"]:
            for diagnostic in artifact["diagnostics"]:
                _conflict(conflicts, "artifact_diagnostic", [],
                          [_location(snapshot, artifact, diagnostic["span"])],
                          f'{diagnostic["code"]}: {diagnostic["detail"]}')
            for declaration in artifact["declarations"]:
                element_id = declaration["element_id"]
                location = _location(snapshot, artifact, declaration["span"])
                if not _eligible(element_id, _location(snapshot, artifact, declaration["label_span"]), conflicts):
                    continue
                if declaration["disposition"] == "definition":
                    observed = (declaration["content_sha256"], location)
                    local[element_id].append(observed)
                    history[element_id].append(observed)
                elif declaration["disposition"] == "occurrence" and declaration["kind"] == "ISS":
                    issues[element_id].append(location)
            for reference in artifact["references"]:
                location = _location(snapshot, artifact, reference["span"])
                targets = [reference["target_id"]]
                if reference["range_end_id"] is not None:
                    targets.append(reference["range_end_id"])
                valid = [_eligible(target, location, conflicts) for target in targets]
                for target, eligible in zip(targets, valid):
                    if eligible and target.startswith("ISS-"):
                        issues[target].append(location)
                if reference["range_end_id"] is not None:
                    _conflict(conflicts, "unsupported_reference_range", targets, [location],
                              "Reference interval is retained without expansion or resolution.")
                elif all(valid):
                    target = reference["target_id"]
                    if not target.startswith("ISS-"):
                        references.append((len(definitions), target, location))
        definitions.append(local)
    return definitions, history, issues, references


def _definition_conflicts(snapshots, definitions, history, conflicts):
    numeric = defaultdict(set)
    for element_id, observations in history.items():
        if len({digest for digest, _ in observations}) > 1:
            _conflict(conflicts, "definition_changed", [element_id],
                      [location for _, location in observations],
                      "Typed content changed; explicit lifecycle/semantic reconciliation is required, not inferred.")
        kind, suffix = element_id.split("-", 1)
        if suffix.isascii() and suffix.isdecimal():
            numeric[(kind, decimal_to_int(suffix))].add(element_id)
    aliases = set()
    for labels in numeric.values():
        if len(labels) > 1:
            aliases.update(labels)
            _conflict(conflicts, "padding_alias", labels,
                      [location for element_id in sorted(labels, key=element_id_sort_key)
                       for _, location in history[element_id]],
                      "Distinct published spellings claim the same positive ordinal; explicit reconciliation is required.")
    for index, local in enumerate(definitions):
        for element_id, observations in local.items():
            locations = [location for _, location in observations]
            if len(observations) > 1:
                _conflict(conflicts, "duplicate_definition", [element_id], locations,
                          "More than one authoritative declaration uses this exact label in the snapshot.")
            if index + 1 < len(definitions) and element_id not in definitions[index + 1]:
                following = snapshots[index + 1]
                original_paths = {location["path"] for location in locations}
                missing = [_location(following, artifact, None)
                           for artifact in following["artifacts"] if artifact["path"] in original_paths]
                _conflict(conflicts, "definition_missing", [element_id], locations + missing,
                          "The next declared snapshot lacks this authoritative definition; retirement is not inferred.")
    return aliases


def inventory_history(request: object) -> dict:
    """Inventory declared snapshots without file/database access or assessment."""
    normalized = _validated_request(request)
    snapshots = [{"snapshot_id": snapshot["snapshot_id"],
                  "artifacts": [_artifact_report(artifact) for artifact in snapshot["artifacts"]]}
                 for snapshot in normalized["snapshots"]]
    conflicts = []
    definitions, history, issues, references = _collect(snapshots, conflicts)
    aliases = _definition_conflicts(snapshots, definitions, history, conflicts)
    for element_id, locations in issues.items():
        _conflict(conflicts, "issue_mapping_required", [element_id], locations,
                  "Every ISS display-label group requires explicit durable-issue mapping; fingerprints transfer no resolution.")
    for index, target, location in references:
        candidates = definitions[index].get(target, [])
        if target in aliases or len(candidates) > 1:
            _conflict(conflicts, "ambiguous_reference", [target],
                      [location] + [source for _, source in candidates],
                      "Duplicate or padding-alias authority prevents unique reference resolution.")
        elif not candidates:
            _conflict(conflicts, "unresolved_reference", [target], [location],
                      "No authoritative declaration for this exact target exists in its declared snapshot.")
    conflicts.sort(key=lambda c: (c["code"], [element_id_sort_key(i) for i in c["element_ids"]],
                                 _json(c["locations"]), c["detail"]))
    return {"report_version": 1, "spec_id": normalized["spec_id"],
            "input_sha256": _sha(_json(normalized)), "coverage": "declared_snapshots_only",
            "source_authentication": "caller_supplied", "assessment": "unassessed",
            "snapshots": snapshots, "conflicts": conflicts}
