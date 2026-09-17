"""Closed input admission for the fresh, local managed discovery proving slice.

The operation owns one coherent inspection and its freshness callbacks. These
helpers select/interpret captured values only: no context regeneration, memory
retrieval, provider dispatch or positive Squad/publication authority lives here.
"""
from copy import deepcopy
import json

import yaml

from echelon.context_builder import CONTEXT_OUTPUT_NAMES
from harness.element_artifacts import parse_identity_artifact


class DiscoveryInputError(ValueError):
    """A bounded reason for refusing unsupported or incomplete runtime inputs."""


class _ConfigLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    pairs = loader.construct_pairs(node)
    result = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise DiscoveryInputError("discovery_config_invalid")
        result[key] = value
    return result


_ConfigLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DiscoveryInputError("discovery_context_invalid")
        result[key] = value
    return result


def runtime_input_paths(root, run_dir):
    """Fixed host-owned sources, including absence observations; no user paths."""
    run = run_dir.relative_to(root).as_posix()
    # Treat `re` as a path observation, not a recursively collected domain. A
    # directory/symlink there fails the regular-file inspector; no RE is read.
    return ((run + "/context", "knowledge-base"),
            (".echelon/config.yml", ".echelon/constitution.md", "re", run + "/evolution-report.md"))


def admit_runtime_inputs(root, run_dir, state, sources):
    """Return detached state context and read-only texts from captured inputs."""
    trees, files = runtime_input_paths(root, run_dir)
    captured_files = {item.path: item.content for item in sources.files}
    captured_trees = {item.path: item for item in sources.trees}
    if not set(files) <= set(captured_files) or not set(trees) <= set(captured_trees):
        raise DiscoveryInputError("discovery_runtime_inputs_unobserved")
    raw = captured_files[".echelon/config.yml"]
    if raw is None or len(raw) > 1024 * 1024:
        raise DiscoveryInputError("discovery_config_required")
    try:
        config = yaml.load(raw.decode("utf-8"), Loader=_ConfigLoader)
    except Exception:
        raise DiscoveryInputError("discovery_config_invalid") from None
    if type(config) is not dict:
        raise DiscoveryInputError("discovery_config_invalid")
    memory = config.get("mempalace", {})
    if type(memory) is not dict or type(memory.get("wing", "")) is not str:
        raise DiscoveryInputError("discovery_memory_configuration_invalid")
    # MemPalaceContext derives its wing from this exact config; `enabled: false`
    # is not an existing disable mechanism and must not mask a configured wing.
    if memory.get("wing", "") != "":
        raise DiscoveryInputError("discovery_external_memory_not_admitted")
    if captured_files["re"] is not None:
        raise DiscoveryInputError("discovery_re_not_admitted")
    if (state.get("mode") != "greenfield"
            or state.get("implementation_targets") != []
            or state.get("requested_re_sources") != []
            or state.get("ignore_re") is not False
            or state.get("product_inputs") != {}
            or "retarget" in state):
        raise DiscoveryInputError("discovery_runtime_domain_not_admitted")
    if "published_re_context" in state:
        re_context = state["published_re_context"]
        if (type(re_context) is not dict
                or re_context != dict(status="absent", generation=0, artifacts={})
                or type(re_context.get("generation")) is not int):
            raise DiscoveryInputError("discovery_re_not_admitted")
    if state.get("context_dir") != str(run_dir / "context"):
        raise DiscoveryInputError("discovery_context_selection_changed")
    if state.get("autonomy_mode") not in {"guided", "semi", "banzai"}:
        raise DiscoveryInputError("discovery_runtime_context_invalid")
    if any(type(state[key]) is not str for key in ("user_message", "user_request") if key in state):
        raise DiscoveryInputError("discovery_runtime_context_invalid")
    if not (state.get("user_request") or state.get("user_message") or "").strip():
        raise DiscoveryInputError("discovery_runtime_context_invalid")
    context_tree = captured_trees[trees[0]]
    required = {trees[0] + "/" + name for name in CONTEXT_OUTPUT_NAMES}
    if (not context_tree.exists or {item.path for item in context_tree.files} != required
            or len(context_tree.directories) != 1):
        raise DiscoveryInputError("discovery_context_incomplete_or_unsupported")
    documents = {item.path: item.content.decode("utf-8")
        for tree in (context_tree, captured_trees["knowledge-base"]) for item in tree.files}
    documents.update((path, captured_files[path].decode("utf-8")) for path in files
        if path not in {".echelon/config.yml", "re"} and captured_files[path] is not None)
    if any("\x00" in text for text in documents.values()):
        raise DiscoveryInputError("discovery_source_not_text")
    try:
        reconciliation = json.loads(documents[trees[0] + "/mempalace-reconciliation.json"], object_pairs_hook=_pairs)
        registry = json.loads(documents[trees[0] + "/feature-registry.snapshot.json"], object_pairs_hook=_pairs)
    except Exception:
        raise DiscoveryInputError("discovery_context_invalid") from None
    if (type(reconciliation) is not dict or reconciliation != dict(accepted_count=0, rejected=[])
            or type(reconciliation.get("accepted_count")) is not int):
        raise DiscoveryInputError("discovery_memory_context_not_admitted")
    request = state.get("user_request", state.get("user_message", ""))
    if type(registry) is not dict or registry != dict(user_request=request, features=[], wip_features=[]):
        # Foreign feature identities cannot become references to same-spelled
        # labels in this spec merely by appearing in a rendered context file.
        raise DiscoveryInputError("discovery_feature_context_not_admitted")
    for path, text in documents.items():
        parsed = parse_identity_artifact(path=path, role="references", text=text)
        if parsed.references or parsed.diagnostics:
            # A captured text is not provenance tying its IDs to this spec.
            # Do not attach stale/foreign context to a same-spelled allocation.
            # Explicit spec-scoped input references retain their separate
            # existing contract; these runtime domains have no such binding.
            raise DiscoveryInputError("discovery_runtime_identity_context_not_admitted")
    keys = ("user_message", "user_request", "mode", "autonomy_mode", "context_dir",
            "implementation_targets", "requested_re_sources", "ignore_re", "published_re_context",
            "product_inputs", "stack_contract", "calibration_map")
    context = deepcopy({key: state[key] for key in keys if key in state})
    if len(json.dumps(context, allow_nan=False).encode("utf-8")) > 128 * 1024:
        raise DiscoveryInputError("discovery_runtime_context_too_large")
    return context, documents
