from __future__ import annotations

from dataclasses import replace
import itertools

from harness.re_v2.protocol_26.model import CheckpointRankV1
from harness.re_v2.protocol_26.selection import (
    RankPolicyRegistryV1,
    compatibility_mismatches,
    select_checkpoints,
)
from tests.re_v2_protocol_22_fixtures import digest, work_item_v2
from tests.re_v2_protocol_26_fixtures import (
    checkpoint_for_item,
    l3_checkpoint_manifest_v1,
    selection_graph,
)


def _test_rank_registry() -> RankPolicyRegistryV1:
    return RankPolicyRegistryV1(
        {
            ("L0", "source-inventory"): lambda candidate: candidate.rank,
        }
    )


def test_candidate_must_equal_expected_work_item_bytes() -> None:
    expected = work_item_v2()
    mutated = replace(
        expected,
        verifier_implementation_digest=digest("different-verifier"),
    )

    assert compatibility_mismatches(expected, mutated) == (
        "verifier_implementation_digest",
    )


def test_quality_vector_wins_then_smallest_hash_breaks_tie() -> None:
    item = work_item_v2()
    policy_hash = digest("test-rank-policy")
    low = checkpoint_for_item(
        item,
        artifact_seed="low-quality",
        origin_run_id="re-low",
        rank_vector=(1,),
        rank_policy_hash=policy_hash,
    )
    high = checkpoint_for_item(
        item,
        artifact_seed="high-quality",
        origin_run_id="re-high",
        rank_vector=(2,),
        rank_policy_hash=policy_hash,
    )
    equal = checkpoint_for_item(
        item,
        artifact_seed="equal-quality",
        origin_run_id="re-equal",
        rank_vector=(2,),
        rank_policy_hash=policy_hash,
    )

    bundle = select_checkpoints(
        selection_graph(item),
        (low, high, equal),
        direct_parent=(),
        rank_registry=_test_rank_registry(),
    )

    assert bundle.selected[0].adopted_artifact_authority.artifact_hash == min(
        high.artifact_hash, equal.artifact_hash
    )
    assert bundle.selected[0].selection_reason == "checkpoint_rank_hash_tiebreak"
    assert {item.reason for item in bundle.alternatives} == {
        "checkpoint_rank_winner",
        "checkpoint_rank_hash_tiebreak",
    }


def test_direct_parent_precedes_stronger_sibling() -> None:
    item = work_item_v2()
    parent = checkpoint_for_item(
        item,
        artifact_seed="parent",
        origin_run_id="re-parent",
        rank_vector=(1,),
    )
    stronger = checkpoint_for_item(
        item,
        artifact_seed="stronger-sibling",
        origin_run_id="re-sibling",
        rank_vector=(99,),
    )

    bundle = select_checkpoints(
        selection_graph(item),
        (stronger,),
        direct_parent=(parent,),
        rank_registry=_test_rank_registry(),
    )

    assert bundle.selected[0].source_kind == "direct_parent"
    assert bundle.selected[0].checkpoint_manifest_id is None
    assert bundle.selected[0].selection_reason == "direct_parent_precedence"
    assert bundle.alternatives[0].reason == "direct_parent_precedence"


def test_downstream_checkpoint_is_dropped_when_dependency_is_missing() -> None:
    upstream_item = work_item_v2()
    upstream = checkpoint_for_item(
        upstream_item,
        artifact_seed="upstream",
        origin_run_id="re-upstream",
    )
    downstream_key = replace(
        upstream_item.output_key,
        dependency_hashes=(upstream.artifact_hash,),
    )
    downstream_item = replace(
        upstream_item,
        template_id=digest("downstream-template"),
        output_key=downstream_key,
        required_artifact_hashes=downstream_key.dependency_hashes,
    )
    downstream = checkpoint_for_item(
        downstream_item,
        artifact_seed="downstream",
        origin_run_id="re-downstream",
        accepted_dependencies=((upstream.artifact_key_id, upstream.artifact_hash),),
    )

    bundle = select_checkpoints(
        selection_graph(upstream_item, downstream_item),
        (downstream,),
        direct_parent=(),
        rank_registry=_test_rank_registry(),
    )

    assert bundle.selected == ()
    assert bundle.rejected[0].reason == "checkpoint_dependency_missing"


def test_dependency_closure_is_topological_and_input_order_independent() -> None:
    upstream_item = work_item_v2()
    upstream = checkpoint_for_item(
        upstream_item,
        artifact_seed="closure-upstream",
        origin_run_id="re-upstream",
    )
    downstream_key = replace(
        upstream_item.output_key,
        dependency_hashes=(upstream.artifact_hash,),
    )
    downstream_item = replace(
        upstream_item,
        template_id=digest("closure-downstream-template"),
        output_key=downstream_key,
        required_artifact_hashes=downstream_key.dependency_hashes,
    )
    downstream = checkpoint_for_item(
        downstream_item,
        artifact_seed="closure-downstream",
        origin_run_id="re-downstream",
        accepted_dependencies=((upstream.artifact_key_id, upstream.artifact_hash),),
    )
    graph = selection_graph(upstream_item, downstream_item)

    bundles = tuple(
        select_checkpoints(
            graph,
            ordering,
            direct_parent=(),
            rank_registry=_test_rank_registry(),
        )
        for ordering in itertools.permutations((upstream, downstream))
    )

    assert len({bundle.identity for bundle in bundles}) == 1
    assert tuple(
        entry.adopted_artifact_authority.artifact_key_id
        for entry in bundles[0].selected
    ) == (upstream.artifact_key_id, downstream.artifact_key_id)


def test_next_ranked_candidate_is_used_when_winner_lacks_dependency() -> None:
    base = work_item_v2()
    upstream = checkpoint_for_item(
        base,
        artifact_seed="fallback-upstream",
        origin_run_id="re-fallback-upstream",
    )
    downstream_key = replace(
        base.output_key,
        artifact_kind="source-partition",
        dependency_hashes=(upstream.artifact_hash,),
    )
    downstream_item = replace(
        base,
        template_id=digest("fallback-downstream-template"),
        output_key=downstream_key,
        required_artifact_hashes=downstream_key.dependency_hashes,
    )
    invalid_winner = checkpoint_for_item(
        downstream_item,
        artifact_seed="invalid-ranked-winner",
        origin_run_id="re-invalid-winner",
        rank_vector=(2,),
        accepted_dependencies=(
            (digest("missing-key"), upstream.artifact_hash),
        ),
    )
    valid_loser = checkpoint_for_item(
        downstream_item,
        artifact_seed="valid-ranked-loser",
        origin_run_id="re-valid-loser",
        rank_vector=(1,),
        accepted_dependencies=(
            (upstream.artifact_key_id, upstream.artifact_hash),
        ),
    )
    registry = RankPolicyRegistryV1(
        {
            ("L0", "source-inventory"): lambda candidate: candidate.rank,
            ("L0", "source-partition"): lambda candidate: candidate.rank,
        }
    )

    bundle = select_checkpoints(
        selection_graph(base, downstream_item),
        (upstream, invalid_winner, valid_loser),
        direct_parent=(),
        rank_registry=registry,
    )

    assert valid_loser.identity in {
        item.checkpoint_manifest_id for item in bundle.selected
    }
    assert bundle.alternatives == ()
    assert bundle.rejected[0].checkpoint_manifest_id == invalid_winner.identity
    assert bundle.rejected[0].reason == "checkpoint_dependency_missing"


def test_unregistered_rank_policy_quarantines_candidate() -> None:
    item = work_item_v2()
    candidate = checkpoint_for_item(
        item,
        artifact_seed="unregistered",
        origin_run_id="re-unregistered",
    )

    bundle = select_checkpoints(
        selection_graph(item),
        (candidate,),
        direct_parent=(),
        rank_registry=RankPolicyRegistryV1({}),
    )

    assert bundle.selected == ()
    assert bundle.quarantined[0].reason == "checkpoint_rank_invalid"


def test_rank_registry_rejects_extractor_that_changes_frozen_policy() -> None:
    item = work_item_v2()
    candidate = checkpoint_for_item(
        item,
        artifact_seed="rank-mismatch",
        origin_run_id="re-rank-mismatch",
    )
    wrong = CheckpointRankV1(1, "wrong-rank", digest("wrong-rank"), (10,))
    registry = RankPolicyRegistryV1(
        {("L0", "source-inventory"): lambda _candidate: wrong}
    )

    bundle = select_checkpoints(
        selection_graph(item),
        (candidate,),
        direct_parent=(),
        rank_registry=registry,
    )

    assert bundle.selected == ()
    assert bundle.quarantined[0].reason == "checkpoint_rank_invalid"


def test_cycle_is_rejected_without_duplicate_alternative_disposition() -> None:
    artifact_a = digest("cycle-a")
    artifact_b = digest("cycle-b")
    base = work_item_v2()
    key_a = replace(base.output_key, dependency_hashes=(artifact_b,))
    key_b = replace(
        base.output_key,
        artifact_kind="source-partition",
        dependency_hashes=(artifact_a,),
    )
    item_a = replace(
        base,
        output_key=key_a,
        required_artifact_hashes=key_a.dependency_hashes,
    )
    item_b = replace(
        base,
        template_id=digest("cycle-template-b"),
        output_key=key_b,
        required_artifact_hashes=key_b.dependency_hashes,
    )
    candidate_a = checkpoint_for_item(
        item_a,
        artifact_seed="cycle-a",
        origin_run_id="re-cycle-a",
        accepted_dependencies=((key_b.identity, artifact_b),),
    )
    candidate_b = checkpoint_for_item(
        item_b,
        artifact_seed="cycle-b",
        origin_run_id="re-cycle-b",
        accepted_dependencies=((key_a.identity, artifact_a),),
    )
    registry = RankPolicyRegistryV1(
        {
            ("L0", "source-inventory"): lambda candidate: candidate.rank,
            ("L0", "source-partition"): lambda candidate: candidate.rank,
        }
    )

    bundle = select_checkpoints(
        selection_graph(item_a, item_b),
        (candidate_a, candidate_b),
        direct_parent=(),
        rank_registry=registry,
    )

    assert bundle.selected == ()
    assert bundle.alternatives == ()
    assert {item.reason for item in bundle.rejected} == {
        "checkpoint_cycle_detected"
    }


def test_l3_epoch_is_never_remapped(tmp_path) -> None:
    candidate = l3_checkpoint_manifest_v1(tmp_path)

    bundle = select_checkpoints(
        selection_graph(
            candidate.work_item,
            target_layer="L3",
            audit_epoch_id=digest("different-audit-epoch"),
        ),
        (candidate,),
        direct_parent=(),
    )

    assert bundle.selected == ()
    assert bundle.rejected[0].reason == "checkpoint_incompatible"
