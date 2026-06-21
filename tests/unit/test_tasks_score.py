import pytest
from lexicon.tasks_score import task_quality

MEASURABLE = """# Tasks: t

- [ ] T-001 complexity=standard phase=p req=REQ-001 depends=none

  **Title:** Do the thing
  **Description:** Build it.
  **Test:** a test asserts latency under 200 ms
  **Acceptance Criteria:**
  - [ ] the list renders within 200 ms for 100 rows
"""

VAGUE = """# Tasks: t

- [ ] T-001 complexity=standard phase=p req=REQ-001 depends=none

  **Title:** Do the thing
  **Description:** Build it.
  **Test:** it is tested
  **Acceptance Criteria:**
  - [ ] the list renders
"""


@pytest.mark.unit
def test_score_is_deterministic():
    assert task_quality(MEASURABLE) == task_quality(MEASURABLE)


@pytest.mark.unit
def test_measurable_scores_higher_than_vague():
    assert task_quality(MEASURABLE)["overall"] > task_quality(VAGUE)["overall"]


@pytest.mark.unit
def test_keys_present_and_bounded():
    q = task_quality(MEASURABLE)
    for k in ("acceptance_measurability", "test_concreteness", "atomicity_ratio",
              "dependency_depth", "overall"):
        assert 0.0 <= q[k] <= 1.0
