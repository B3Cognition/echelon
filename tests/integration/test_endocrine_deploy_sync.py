"""Spec 025-endocrine-deploy-sync — regression test + CI guard.

Covers FR-001..FR-015 + SC-001..SC-005 from
`specs/025-endocrine-deploy-sync/spec.md`.

Test → Requirement mapping:
  test_source_deployed_byte_identical
      FR-005, FR-012, SC-002, SC-005
  test_deployed_lacks_vulnerable_resolver_pattern
      FR-006, SC-003
  test_deployed_init_produces_archetype_baselines
      FR-002, FR-003, FR-004, FR-013, FR-014, SC-001, SC-004
  test_skip_gracefully_if_deployed_missing
      FR-011

FR-007/008/009 are negative "shall NOT modify" requirements satisfied by
the change not touching those things; no test scaffolding required.

FR-010 is satisfied by this module not requiring `specify` to be installed.

FR-015 (safety-default 0.5 fallback when baselines absent) is covered by
the existing endocrine unit tests in tests/unit/test-endocrine-*.sh.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SCRIPT = REPO_ROOT / "extension" / "scripts" / "bash" / "endocrine.sh"
DEPLOYED_SCRIPT = (
    REPO_ROOT
    / ".specify"
    / "extensions"
    / "echelon"
    / "scripts"
    / "bash"
    / "endocrine.sh"
)

pytestmark = [pytest.mark.integration, pytest.mark.deployed_extension]

_RESOLVER_ANTIPATTERN = re.compile(
    r'eval\s+"\$\([^)]*specify[^)]*\)"\s*(?:2>/dev/null)?\s*\\?\s*&&\s*_ECHELON_RESOLVER_OK=true'
)


def test_source_deployed_byte_identical():
    """FR-005, SC-002, SC-005: source and deployed copies must be byte-identical."""
    src = SOURCE_SCRIPT.read_bytes()
    dep = DEPLOYED_SCRIPT.read_bytes()
    assert src == dep, (
        "endocrine.sh source/deployed divergence detected.\n"
        f"  source:   {SOURCE_SCRIPT}  ({len(src)} bytes)\n"
        f"  deployed: {DEPLOYED_SCRIPT}  ({len(dep)} bytes)\n"
        "Fix:\n"
        f"  cp {SOURCE_SCRIPT} {DEPLOYED_SCRIPT}\n"
        f"  (or:  specify extension update --dev {REPO_ROOT / 'extension'})"
    )


def test_deployed_lacks_vulnerable_resolver_pattern():
    """FR-006, SC-003: deployed copy must not contain the pre-df99b73 antipattern.

    The antipattern `eval "$(cmd)" && _ECHELON_RESOLVER_OK=true` sets the flag
    when `cmd` produces empty stdout, because `eval ""` returns exit 0. This
    is the failure mode that caused the original DEP-FAIL-1 bug — every agent
    received 0.5 safety-default baselines instead of archetype-specific values.
    """
    content = DEPLOYED_SCRIPT.read_text()
    match = _RESOLVER_ANTIPATTERN.search(content)
    assert match is None, (
        "Deployed endocrine.sh contains the vulnerable resolver-gate antipattern.\n"
        f"  file:  {DEPLOYED_SCRIPT}\n"
        f"  match: {match.group(0) if match else ''!r}\n"
        "The `eval \"$(cmd)\" && _ECHELON_RESOLVER_OK=true` pattern sets the\n"
        "flag when cmd produces empty stdout (eval of '' returns 0). Fix:\n"
        "use `if _resolver_out=$(cmd); then ... fi` to propagate exit codes."
    )


def test_deployed_init_produces_archetype_baselines(tmp_path):
    """FR-002/003/004/013/014, SC-001/004: deployed init produces archetype-correct baselines.

    Runs `bash endocrine.sh init` against a temp state file via subprocess
    (mimicking the COMMANDER bootstrap dispatch path) and asserts each
    expected archetype's hormone profile lands in state.
    """
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"phase": "test"}))

    env = os.environ.copy()
    env["ENDOCRINE_STATE_FILE"] = str(state_file)

    result = subprocess.run(
        ["bash", str(DEPLOYED_SCRIPT), "init"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"deployed endocrine.sh init failed (exit {result.returncode})\n"
        f"  stdout: {result.stdout}\n"
        f"  stderr: {result.stderr}"
    )

    state = json.loads(state_file.read_text())
    agents = state.get("endocrine_state", {}).get("agents", {})
    assert agents, "no agents seeded after init"

    # FR-004: GOLDDIGGER (exploration archetype)
    g = agents.get("GOLDDIGGER", {}).get("hormones", {})
    assert g.get("dopamine") == 0.7, (
        f"GOLDDIGGER dopamine: expected 0.7 (exploration baseline), got {g.get('dopamine')!r}"
    )
    assert g.get("cortisol") == 0.3, (
        f"GOLDDIGGER cortisol: expected 0.3, got {g.get('cortisol')!r}"
    )
    assert g.get("norepinephrine") == 0.4, (
        f"GOLDDIGGER norepinephrine: expected 0.4, got {g.get('norepinephrine')!r}"
    )

    # FR-013: GUARDIAN (validation archetype)
    gd = agents.get("GUARDIAN", {}).get("hormones", {})
    assert gd.get("dopamine") == 0.3, (
        f"GUARDIAN dopamine: expected 0.3 (validation baseline), got {gd.get('dopamine')!r}"
    )
    assert gd.get("cortisol") == 0.8, (
        f"GUARDIAN cortisol: expected 0.8, got {gd.get('cortisol')!r}"
    )
    assert gd.get("norepinephrine") == 0.7, (
        f"GUARDIAN norepinephrine: expected 0.7, got {gd.get('norepinephrine')!r}"
    )

    # FR-014: MAVERICK (innovation archetype)
    m = agents.get("MAVERICK", {}).get("hormones", {})
    assert m.get("dopamine") == 0.8, (
        f"MAVERICK dopamine: expected 0.8 (innovation baseline), got {m.get('dopamine')!r}"
    )
    assert m.get("cortisol") == 0.2, (
        f"MAVERICK cortisol: expected 0.2, got {m.get('cortisol')!r}"
    )
    assert m.get("norepinephrine") == 0.3, (
        f"MAVERICK norepinephrine: expected 0.3, got {m.get('norepinephrine')!r}"
    )

    # SC-004: no agent whose archetype is NOT `control` may end up with all
    # six hormones at the 0.5 safety-default. The `control` archetype
    # legitimately has [0.5]*6 as its baseline (per echelon-config.yml).
    six = ("adrenaline", "dopamine", "cortisol", "serotonin", "oxytocin", "norepinephrine")
    homogenized = []
    for name, rec in agents.items():
        archetype = rec.get("archetype")
        if archetype == "control":
            continue
        h = rec.get("hormones", {})
        if all(h.get(k) == 0.5 for k in six):
            homogenized.append(f"{name} (archetype={archetype})")
    assert not homogenized, (
        f"Non-control-archetype agents incorrectly stamped with safety-default 0.5: {homogenized}\n"
        "This indicates the resolver-gate regression or baselines config is missing."
    )


def test_deployed_copy_exists():
    """FR-011: this module is only collected when the deployed copy exists."""
    assert DEPLOYED_SCRIPT.exists()
