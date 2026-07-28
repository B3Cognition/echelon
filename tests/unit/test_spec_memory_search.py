from pathlib import Path

import pytest


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.gets = []

    def query(self, query_texts, n_results, where, include):
        self.queries.append(
            {
                "query_texts": query_texts,
                "n_results": n_results,
                "where": where,
                "include": include,
            }
        )
        matches = [
            row
            for row in self.rows
            if _matches_where(row["metadata"], where)
        ][:n_results]
        return {
            "ids": [[row["id"] for row in matches]],
            "documents": [[row["document"] for row in matches]],
            "metadatas": [[row["metadata"] for row in matches]],
            "distances": [[row.get("distance", 0.1) for row in matches]],
        }

    def get(self, where=None, include=None, limit=None):
        self.gets.append({"where": where, "include": include, "limit": limit})
        matches = [
            row
            for row in self.rows
            if where is None or _matches_where(row["metadata"], where)
        ][:limit]
        return {
            "ids": [row["id"] for row in matches],
            "documents": [row["document"] for row in matches],
            "metadatas": [row["metadata"] for row in matches],
        }


class FakeAdapter:
    wing = "demo-wing"
    palace_path = Path(".mempalace")

    def __init__(self, collection):
        self.collection = collection

    def open_collection_read_only(self):
        return self.collection


def _matches_where(metadata, where):
    if "$and" in where:
        return all(_matches_where(metadata, clause) for clause in where["$and"])
    for key, condition in where.items():
        if isinstance(condition, dict) and "$eq" in condition:
            if metadata.get(key) != condition["$eq"]:
                return False
        elif metadata.get(key) != condition:
            return False
    return True


def _rows():
    return [
        {
            "id": "drawer-fr",
            "document": "FR-001: Import prose artifacts.",
            "distance": 0.11,
            "metadata": {
                "wing": "demo-wing",
                "room": "functional-requirements",
                "artifact_path": "specs/905-import-prose/spec.md",
                "requirement_id": "FR-001",
                "artifact_kind": "requirement",
            },
        },
        {
            "id": "drawer-plan",
            "document": "CTX-plan-000: Plan: Implement FR-001.",
            "distance": 0.2,
            "metadata": {
                "wing": "demo-wing",
                "room": "implementation-plan",
                "artifact_path": "specs/905-import-prose/plan.md",
                "requirement_id": "CTX-plan-000",
                "artifact_kind": "supporting-context",
            },
        },
        {
            "id": "drawer-other",
            "document": "FR-002: Other spec.",
            "distance": 0.05,
            "metadata": {
                "wing": "demo-wing",
                "room": "functional-requirements",
                "artifact_path": "specs/909-expose-supported-machine-readable/spec.md",
                "requirement_id": "FR-002",
                "artifact_kind": "requirement",
            },
        },
    ]


@pytest.mark.unit
def test_search_filters_by_room_spec_and_kind(monkeypatch, tmp_path: Path) -> None:
    collection = FakeCollection(_rows())
    monkeypatch.setattr(
        "echelon.spec_memory_search.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(collection),
    )
    from echelon.spec_memory_search import search_spec_memory

    report = search_spec_memory(
        tmp_path,
        "import",
        room="functional-requirements",
        spec="905-import-prose",
        kind="requirement",
        limit=10,
    )

    assert [hit.drawer_id for hit in report.hits] == ["drawer-fr"]
    assert report.hits[0].spec_id == "905-import-prose"
    assert collection.queries[0]["where"] == {
        "$and": [
            {"wing": {"$eq": "demo-wing"}},
            {"room": {"$eq": "functional-requirements"}},
        ]
    }


@pytest.mark.unit
def test_list_facets_extracts_rooms_specs_and_kinds(monkeypatch, tmp_path: Path) -> None:
    collection = FakeCollection(_rows())
    monkeypatch.setattr(
        "echelon.spec_memory_search.create_requirement_memory_adapter",
        lambda project_root, run_id: FakeAdapter(collection),
    )
    from echelon.spec_memory_search import list_spec_memory_facets

    facets = list_spec_memory_facets(tmp_path)

    assert facets.rooms == {
        "functional-requirements": 2,
        "implementation-plan": 1,
    }
    assert facets.specs == {
        "905-import-prose": 2,
        "909-expose-supported-machine-readable": 1,
    }
    assert facets.kinds == {"requirement": 2, "supporting-context": 1}
