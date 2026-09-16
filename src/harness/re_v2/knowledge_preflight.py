"""Local whole-journey planning heuristic; never a dispatch/accounting policy.

Inventory is provisional: discovery can find additional domains. The allowance
includes source discovery, production, review/repair and workspace synthesis.
Repeated tool/cache context is charged by some providers, so source text alone
is not a useful aggregate ceiling. No provider calls or repository reads occur.
"""

from dataclasses import dataclass
from typing import Mapping

from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1


@dataclass(frozen=True, slots=True)
class KnowledgeRequestEstimate:
    source_count: int
    file_count: int
    line_count: int
    text_bytes: int
    domain_count: int
    lower_tokens: int
    upper_tokens: int
    recommended_tokens: int


def estimate_knowledge_request(
    partition: WorkspacePartitionCatalogV1,
    source_depths: Mapping[str, str],
    *,
    retained_source_count: int = 0,
    synthesis_required: bool = True,
) -> KnowledgeRequestEstimate:
    """Estimate only selected/reanalyzed sources plus one workspace synthesis.

    This is an intentionally conservative initial heuristic, not a statistical
    confidence interval or guarantee. Calibrate against whole-request telemetry
    rather than adding expensive per-dispatch estimation.
    """
    sources = {source.source_id: source for source in partition.sources}
    if set(source_depths) - sources.keys():
        raise ValueError("preflight selection contains an unknown source")
    if retained_source_count < 0:
        raise ValueError("retained source count must be nonnegative")
    multipliers = {"quick": 1, "standard": 2, "deep": 4}
    files = lines = text_bytes = domains = source_work = 0
    for source_id, depth in source_depths.items():
        if depth not in multipliers:
            raise ValueError("preflight depth must be quick, standard, or deep")
        source = sources[source_id]
        eligible = tuple(file for file in source.files
                         if file.object_kind == "regular"
                         and file.text_status == "eligible_utf8")
        size = sum(file.byte_count for file in eligible)
        files += len(eligible)
        lines += sum(file.line_count for file in eligible)
        text_bytes += size
        domains += len(source.domains)
        approximate_text_tokens = (size + 3) // 4
        nominal = 500_000 + 250_000 * len(source.domains) + 32 * approximate_text_tokens
        source_work += (nominal * multipliers[depth] + 1) // 2
    nominal_total = source_work
    if synthesis_required:
        nominal_total += 1_000_000 + 100_000 * retained_source_count
    upper = nominal_total * 2
    recommended = ((upper + 999_999) // 1_000_000) * 1_000_000
    return KnowledgeRequestEstimate(len(source_depths), files, lines, text_bytes,
                                    domains, nominal_total, upper, recommended)
