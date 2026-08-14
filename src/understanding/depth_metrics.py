#!/usr/bin/env python3
"""
Specification Depth Metrics - Measures thoroughness beyond ratios.

Three metrics that distinguish comprehensive squad specs from minimal specs:
1. Requirement Volume Score (RVS): logarithmic count of distinct requirements
2. Coverage Density (CD): requirements per unique domain concept
3. Cross-Reference Index (CRI): internal requirement cross-references

These metrics reward specs that have MORE requirements, cover MORE concepts,
and have MORE interconnection between requirements.
"""

import math
import re
from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class DepthMetrics:
    """Specification depth metrics."""
    requirement_volume_score: float  # 0-1, log scale
    coverage_density: float  # 0-1, saturating
    cross_reference_index: float  # 0-1, saturating
    depth_score: float  # weighted composite

    def to_dict(self) -> Dict[str, float]:
        return {
            "requirement_volume_score": round(self.requirement_volume_score, 4),
            "coverage_density": round(self.coverage_density, 4),
            "cross_reference_index": round(self.cross_reference_index, 4),
            "depth_score": round(self.depth_score, 4),
        }


class DepthAnalyzer:
    """Analyzes specification depth across three dimensions."""

    # Requirement ID pattern for cross-reference detection
    # Service-level projection supplies this analyzer only known requirement
    # identifiers and explicit dependencies, so Lexicon's generic `R1` and
    # `TASK-07` forms are safe to recognise here.
    REQ_ID_PATTERN = re.compile(r'(?:[A-Z][A-Z0-9]*(?:-\d+)+|[A-Z]+\d+)')

    def extract_dependency_graph(self, requirements: List[str]) -> Dict[str, List[str]]:
        """
        Build an adjacency dict of cross-references between requirements.

        Each requirement that contains a recognizable ID (e.g. FR-001) is
        keyed by that ID.  Its value is the list of *other* requirement IDs
        referenced in its text.

        Args:
            requirements: List of requirement strings

        Returns:
            Dict mapping requirement ID -> list of referenced IDs
        """
        # First pass: discover the "owning" ID for each requirement.
        # Heuristic: the first ID token in the string is the requirement's own ID.
        req_own_ids: List[str | None] = []
        all_known_ids: set = set()

        for req in requirements:
            ids_in_req = self.REQ_ID_PATTERN.findall(req)
            own_id = ids_in_req[0] if ids_in_req else None
            req_own_ids.append(own_id)
            all_known_ids.update(ids_in_req)

        # Second pass: for each requirement with an own ID, find references to
        # other known IDs.
        graph: Dict[str, List[str]] = {}
        for idx, req in enumerate(requirements):
            own_id = req_own_ids[idx]
            if own_id is None:
                continue
            ids_in_req = self.REQ_ID_PATTERN.findall(req)
            refs = [rid for rid in ids_in_req if rid != own_id and rid in all_known_ids]
            graph[own_id] = refs

        return graph

    def analyze(self, requirements: List[str], full_text: str, unique_concepts: int = 0) -> DepthMetrics:
        """Analyze specification depth.

        Args:
            requirements: List of individual requirement strings.
            full_text: The full specification text (used for cross-ref detection).
            unique_concepts: Number of unique domain concepts covered.

        Returns:
            DepthMetrics with all three metrics and composite score.
        """
        if not requirements:
            return DepthMetrics(0.0, 0.0, 0.0, 0.0)

        n = len(requirements)

        # RVS: min(1.0, log(1 + n) / log(1 + 200))
        # 5 reqs = 0.34, 20 = 0.57, 50 = 0.74, 100 = 0.87, 200 = 1.0
        rvs = min(1.0, math.log(1 + n) / math.log(1 + 200))

        # CD: 1 - exp(-reqs_per_concept / 3.0)
        concepts = max(unique_concepts, 1)
        reqs_per_concept = n / concepts
        cd = 1.0 - math.exp(-reqs_per_concept / 3.0)

        # CRI: count cross-references between requirements
        # Extract all req IDs from full text
        all_ids = set(self.REQ_ID_PATTERN.findall(full_text))

        cross_refs = 0
        for i, req in enumerate(requirements):
            # Find IDs referenced in this requirement
            refs_in_req = set(self.REQ_ID_PATTERN.findall(req))
            # Count references to OTHER requirement IDs (not self)
            # We can't know which ID belongs to this req, so count all refs
            cross_refs += len(refs_in_req & all_ids)

        # Subtract self-references (each req that HAS an ID references itself)
        # Approximate: one self-ref per req that contains an ID
        self_refs = sum(1 for req in requirements if self.REQ_ID_PATTERN.search(req))
        cross_refs = max(0, cross_refs - self_refs)

        # Explicit lexicon `DEPENDS:` links are genuine inter-requirement
        # cross-references. The markdown requirement extractor flattens REQ
        # blocks to GIVEN/WHEN/THEN prose and drops the DEPENDS line, so read
        # those links from the full spec text directly. `DEPENDS: none` declares
        # no dependency and contributes nothing.
        for line in full_text.splitlines():
            m = re.match(r"\s*DEPENDS:\s*(.+)", line)
            if m and m.group(1).strip().lower() != "none":
                cross_refs += len(self.REQ_ID_PATTERN.findall(m.group(1)))

        cri = 1.0 - math.exp(-cross_refs / max(n, 1))

        # Composite: weighted average
        depth_score = 0.40 * rvs + 0.35 * cd + 0.25 * cri

        return DepthMetrics(rvs, cd, cri, depth_score)
