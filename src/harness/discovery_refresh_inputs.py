"""Pure semantic dependency comparison; never dispatch or publication authority.

Callers must authenticate accepted postimages and all live source guards first.
The ordinary operation fingerprint remains authoritative for replay/publication;
these narrower digests answer only whether a dependency needs refreshing.
"""
from copy import deepcopy
import hashlib
import json


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def dependency_view(*, trees, files, history, spec_path, run_path, runtime):
    """Describe captured semantic inputs, preserving exact identity/evidence.

    Generated runtime renderings, checkpoint metadata and the derived graph are
    authenticated by the caller, but are not independent semantic inputs. Their
    source artifacts, admitted runtime policy and clarification files are.
    Missing files remain distinguishable from present empty files. Publication
    owner IDs and ledger entry ordering are not identity revisions or evidence.
    """
    def derived(path):
        return (path == spec_path + "/spec-artifact-graph.json"
            or path == spec_path + "/.echelon" or path.startswith(spec_path + "/.echelon/")
            or path == run_path + "/context" or path.startswith(run_path + "/context/"))
    result = {}
    for tree in trees:
        if derived(tree.path):
            continue
        result["tree:" + tree.path] = _digest(dict(exists=tree.exists,
            directories=sorted(item.path for item in tree.directories if not derived(item.path))))
        for item in tree.files:
            if not derived(item.path):
                result["file:" + item.path] = hashlib.sha256(item.content).hexdigest()
    for item in files:
        if item.content is not None and not derived(item.path):
            result["file:" + item.path] = hashlib.sha256(item.content).hexdigest()
    if hashlib.sha256(history.payload.encode("ascii")).hexdigest() != history.sha256:
        raise ValueError("invalid dependency history")
    identity = deepcopy(json.loads(history.payload))
    for key in ("revisions", "lineage", "reference_claims", "issue_occurrences"):
        # Binding payload hashes include the owner and entry index. Their exact
        # rows are authenticated upstream; retaining those hashes here would
        # indirectly reintroduce the bookkeeping fields removed below.
        bookkeeping = {"operation_id", "entry_index"}
        if key in {"reference_claims", "issue_occurrences"}:
            bookkeeping.add("payload_sha256")
        identity[key] = sorted(({name: value for name, value in row.items()
            if name not in bookkeeping} for row in identity[key]), key=_json)
    identity["entities"] = sorted(identity["entities"], key=_json)
    result["identity"] = _digest(identity)
    result["runtime"] = _digest(runtime)
    return result


def compare_dependencies(before, after):
    """Retain a deterministic decision, not a second source snapshot ledger."""
    return dict(before_sha256=_digest(before), after_sha256=_digest(after),
        changed=sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key)))
