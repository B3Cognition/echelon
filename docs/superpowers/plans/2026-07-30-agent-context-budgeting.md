# Agent Context Budgeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build phase-aware bounded agent context rendering, telemetry, and benchmark render-mode comparison for Echelon without destabilizing normal flow.

**Architecture:** Add a focused `harness.agent_context` module that owns selector parsing, policy selection, bounded rendering, and telemetry records. `squad_executors.py` should delegate context-pack rendering to that module for both normal and staged prompts, while preserving the existing prompt assembly order and routing/result contracts. `echelon.benchmark` then receives a context-render option that propagates `ECHELON_CONTEXT_RENDER_MODE` into benchmark commands and can run legacy and bounded variants from the same baseline.

**Tech Stack:** Python 3.11+, dataclasses, pathlib, json/jsonl, pytest, Typer CLI wrappers, existing Echelon harness modules.

## Global Constraints

- Default runtime behavior is warn-and-truncate, not fail-closed.
- Only one prompt is sent to the provider during normal dispatch.
- Render both legacy and bounded prompt metrics locally, but do not persist full prompt bodies by default.
- Bounding must be phase/node-aware. Do not apply one uniform first-N truncation policy.
- Preserve current normative artifacts before historical context.
- Existing workflow `context_pack` filter syntax must remain valid.
- Existing unfiltered context-pack entries must continue to work, but bounded.
- Benchmark `--context-render both` is the only mode that intentionally runs a fixture twice.
- Do not rewrite `extension/workflow/definition.yaml` in bulk.
- Leave unrelated worktree changes alone.

---

## File Structure

- Create `src/harness/agent_context.py`
  - Owns context selector parsing, render mode resolution, policy selection, bounded rendering, prompt section metrics, and context budget report writing.
  - Exposes small functions/classes consumed by executors and benchmarks.

- Modify `src/harness/squad_executors.py`
  - Replace local `_context_pack_filters`, `_render_reasoning_journal_context`, `_render_why_state_context`, and direct `_render_context_candidate` logic with calls into `harness.agent_context`.
  - Use the same renderer for `AgentExecutor._assemble_prompt` and `StagedParallelExecutor._build_agent_prompt`.

- Modify `src/echelon/benchmark.py`
  - Add `context_render` support to benchmark planning and execution.
  - Add `both` orchestration by running legacy and bounded records from the same baseline snapshot.
  - Summarize context-render metrics from context budget reports when available.

- Modify `src/echelon/cli.py`
  - Parse `--context-render legacy|bounded|both` for legacy CLI benchmark commands.

- Modify `src/echelon/cli_app.py`
  - Add Typer option `--context-render`.

- Add `tests/unit/test_agent_context.py`
  - Unit tests for selectors, phase policies, state projection, bounded rendering, telemetry reports, and render mode.

- Modify `tests/kernel/test_squad_executors_journal.py`
  - Regression tests proving bounded context applies to normal and staged prompts.

- Modify `tests/unit/test_benchmark.py`
  - Benchmark CLI and runner tests for `legacy`, `bounded`, and `both`.

---

### Task 1: Agent Context Selector and Policy Core

**Files:**
- Create: `src/harness/agent_context.py`
- Test: `tests/unit/test_agent_context.py`

**Interfaces:**
- Produces:
  - `ContextSelector(path_ref: str, filters: dict[str, str])`
  - `parse_context_pack_item(item: str) -> ContextSelector`
  - `ContextPolicy(criticality: str, renderer: str, cap_bytes: int, overflow_action: str)`
  - `policy_for_context(phase_id: str, agent_id: str, mode: str, path_ref: str) -> ContextPolicy`
  - `resolve_context_render_mode(env: Mapping[str, str] | None = None) -> str`
- Consumes: no project-specific runtime state.

- [ ] **Step 1: Write failing selector parsing tests**

Add to `tests/unit/test_agent_context.py`:

```python
from harness.agent_context import (
    parse_context_pack_item,
    policy_for_context,
    resolve_context_render_mode,
)


def test_parse_context_pack_item_extracts_filters_and_path() -> None:
    selector = parse_context_pack_item(
        ".specify/squad/reasoning-journal.jsonl [type=routing_decision, phase=phase1-what]"
    )

    assert selector.path_ref == ".specify/squad/reasoning-journal.jsonl"
    assert selector.filters == {
        "type": "routing_decision",
        "phase": "phase1-what",
    }


def test_parse_context_pack_item_preserves_glob_path() -> None:
    selector = parse_context_pack_item("adr/ADR-*.md")

    assert selector.path_ref == "adr/ADR-*.md"
    assert selector.filters == {}


def test_resolve_context_render_mode_defaults_to_bounded() -> None:
    assert resolve_context_render_mode({}) == "bounded"


def test_resolve_context_render_mode_accepts_legacy() -> None:
    assert resolve_context_render_mode({"ECHELON_CONTEXT_RENDER_MODE": "legacy"}) == "legacy"


def test_resolve_context_render_mode_rejects_unknown() -> None:
    assert resolve_context_render_mode({"ECHELON_CONTEXT_RENDER_MODE": "strange"}) == "bounded"


def test_policy_for_why2_preserves_spec() -> None:
    policy = policy_for_context(
        phase_id="phase1-why2",
        agent_id="speckit-echelon-sage",
        mode="WHY2",
        path_ref="{spec_dir}/spec.md",
    )

    assert policy.criticality == "must_preserve"
    assert policy.renderer == "full_file"
    assert policy.overflow_action == "legacy_fallback_warning"


def test_policy_for_journal_history_is_bounded() -> None:
    policy = policy_for_context(
        phase_id="phase1-why2",
        agent_id="speckit-echelon-sage",
        mode="WHY2",
        path_ref=".specify/squad/reasoning-journal.jsonl",
    )

    assert policy.criticality == "history"
    assert policy.renderer == "filtered_journal"
    assert policy.overflow_action == "truncate_with_notice"
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `PYTHONPATH=src pytest tests/unit/test_agent_context.py -v`

Expected: import failure because `harness.agent_context` does not exist.

- [ ] **Step 3: Implement the selector and policy core**

Create `src/harness/agent_context.py`:

```python
"""Phase-aware bounded rendering for Echelon agent dispatch context."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


RENDER_MODES = {"bounded", "legacy"}


@dataclass(frozen=True)
class ContextSelector:
    path_ref: str
    filters: dict[str, str]


@dataclass(frozen=True)
class ContextPolicy:
    criticality: str
    renderer: str
    cap_bytes: int
    overflow_action: str


DEFAULT_FILE_CAP_BYTES = 96 * 1024
DEFAULT_HISTORY_CAP_BYTES = 24 * 1024
DEFAULT_DIRECTORY_CAP_BYTES = 96 * 1024
MUST_PRESERVE_CAP_BYTES = 512 * 1024


def resolve_context_render_mode(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    mode = str(source.get("ECHELON_CONTEXT_RENDER_MODE") or "bounded").strip().lower()
    return mode if mode in RENDER_MODES else "bounded"


def parse_context_pack_item(item: str) -> ContextSelector:
    raw = str(item or "").strip()
    filters: dict[str, str] = {}
    match = re.search(r"\[([^\]]+)\]", raw)
    if match:
        for part in match.group(1).split(","):
            key, separator, value = part.partition("=")
            if separator and key.strip() and value.strip():
                filters[key.strip()] = value.strip()
        raw = raw[: match.start()].strip()
    path_ref = raw.split(" ")[0].split("(")[0].rstrip()
    return ContextSelector(path_ref=path_ref, filters=filters)


def policy_for_context(
    *,
    phase_id: str,
    agent_id: str = "",
    mode: str = "",
    path_ref: str,
) -> ContextPolicy:
    ref = path_ref.strip()
    basename = Path(ref.rstrip("/")).name
    phase = phase_id.strip()

    if "reasoning-journal.jsonl" in ref:
        return ContextPolicy("history", "filtered_journal", DEFAULT_HISTORY_CAP_BYTES, "truncate_with_notice")

    if basename == "state.json":
        return ContextPolicy("important", "compact_json", DEFAULT_FILE_CAP_BYTES, "summarize_with_notice")

    if ref.endswith("/") or any(ch in ref for ch in "*?[]"):
        if "contracts" in ref:
            return ContextPolicy("must_preserve", "directory_bounded_files", DEFAULT_DIRECTORY_CAP_BYTES, "manifest_only")
        if "investigation" in ref:
            return ContextPolicy("important", "directory_bounded_files", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")
        if "adr/" in ref or "ADR-" in ref:
            return ContextPolicy("important", "directory_bounded_files", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")
        return ContextPolicy("important", "directory_manifest", DEFAULT_DIRECTORY_CAP_BYTES, "manifest_only")

    if phase == "phase1-why2" and basename in {"spec.md", "constitution.md", "assumptions.md"}:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if phase == "phase1-investigate" and basename in {"spec.md", "assumptions.md", "unknowns.md", "issues.md"}:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if phase in {"phase3-sentinel", "phase3-consensus"} and basename in {
        "spec.md",
        "plan.md",
        "data-model.md",
        "tasks.md",
        "coverage-map.md",
        "test-strategy.md",
        "critical-path.md",
        "risk-matrix.md",
        "dependencies.md",
    }:
        return ContextPolicy("must_preserve", "full_file", MUST_PRESERVE_CAP_BYTES, "legacy_fallback_warning")

    if basename in {"prior-spec-context.md", "stale-memory-report.md"}:
        return ContextPolicy("advisory", "summary_pointer", DEFAULT_HISTORY_CAP_BYTES, "summarize_with_notice")

    return ContextPolicy("important", "full_file", DEFAULT_FILE_CAP_BYTES, "truncate_with_notice")
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `PYTHONPATH=src pytest tests/unit/test_agent_context.py -v`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/agent_context.py tests/unit/test_agent_context.py
git commit -m "feat: add agent context policy core"
```

---

### Task 2: Bounded Journal, State, File, and Directory Rendering

**Files:**
- Modify: `src/harness/agent_context.py`
- Test: `tests/unit/test_agent_context.py`

**Interfaces:**
- Consumes:
  - `ContextSelector`
  - `ContextPolicy`
- Produces:
  - `RenderedSection(title: str, text: str, bytes: int, omitted: dict[str, int | str])`
  - `render_journal(path: Path, filters: Mapping[str, str], cap_bytes: int) -> RenderedSection`
  - `compact_state_projection(state: Mapping[str, object], phase_id: str, allowed_state_updates: object = None) -> dict[str, object]`
  - `render_context_path(path_ref: str, candidate: Path, policy: ContextPolicy, filters: Mapping[str, str], state: Mapping[str, object] | None = None, phase_id: str = "") -> RenderedSection`

- [ ] **Step 1: Write failing rendering tests**

Append to `tests/unit/test_agent_context.py`:

```python
import json
from pathlib import Path

from harness.agent_context import (
    ContextPolicy,
    compact_state_projection,
    render_context_path,
    render_journal,
)


def test_render_journal_filters_phase_and_type(tmp_path: Path) -> None:
    journal = tmp_path / "reasoning-journal.jsonl"
    journal.write_text(
        "\n".join(
            [
                json.dumps({"type": "decision", "phase": "phase1-what", "data": {"keep": True}}),
                json.dumps({"type": "decision", "phase": "phase1-old", "data": {"drop": True}}),
                json.dumps({"type": "insight", "phase": "phase1-what", "data": {"drop": True}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    section = render_journal(
        journal,
        {"type": "routing_decision", "phase": "phase1-what"},
        cap_bytes=4096,
    )

    assert '"keep": true' in section.text
    assert "phase1-old" not in section.text
    assert '"type": "insight"' not in section.text
    assert section.omitted["matched"] == 1


def test_render_journal_supports_phase_wildcard(tmp_path: Path) -> None:
    journal = tmp_path / "reasoning-journal.jsonl"
    journal.write_text(
        json.dumps({"type": "decision", "phase": "phase1-why1"}) + "\n"
        + json.dumps({"type": "decision", "phase": "phase2-decide"}) + "\n",
        encoding="utf-8",
    )

    section = render_journal(journal, {"phase": "phase1-*"}, cap_bytes=4096)

    assert "phase1-why1" in section.text
    assert "phase2-decide" not in section.text


def test_compact_state_projection_excludes_large_ledgers() -> None:
    state = {
        "phase": "phase1-why2",
        "spec_id": "001-demo",
        "squad_dir": "/tmp/run",
        "issue_resolution_ledger": {
            "ISS-1": {"status": "validated", "guidance": "x" * 10_000},
        },
        "token_ledger": {"dispatches": [{"raw": "x" * 10_000}]},
    }

    projection = compact_state_projection(state, "phase1-why2")

    assert projection["phase"] == "phase1-why2"
    assert projection["issue_resolution_statuses"] == {"ISS-1": "validated"}
    assert "issue_resolution_ledger" not in projection
    assert "token_ledger" not in projection


def test_render_contracts_directory_preserves_manifest_when_body_capped(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "a.md").write_text("# A\n" + "a" * 5000, encoding="utf-8")
    (contracts / "b.md").write_text("# B\n" + "b" * 5000, encoding="utf-8")
    policy = ContextPolicy("must_preserve", "directory_bounded_files", 512, "manifest_only")

    section = render_context_path("contracts/", contracts, policy, {}, phase_id="phase3-sentinel")

    assert "## Directory manifest" in section.text
    assert "a.md" in section.text
    assert "b.md" in section.text
    assert section.omitted["truncated"] == "true"
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `PYTHONPATH=src pytest tests/unit/test_agent_context.py -v`

Expected: failures for missing rendering functions/classes.

- [ ] **Step 3: Implement rendering functions**

Extend `src/harness/agent_context.py`:

```python
import fnmatch
import json
from dataclasses import asdict
from typing import Any


@dataclass(frozen=True)
class RenderedSection:
    title: str
    text: str
    bytes: int
    omitted: dict[str, int | str]


STATE_ALWAYS_KEYS = (
    "run_id",
    "spec_id",
    "phase",
    "status",
    "iteration",
    "max_iterations",
    "autonomy_mode",
    "squad_dir",
    "staging_dir",
    "context_dir",
    "spec_dir",
    "published_spec_dir",
    "implementation_targets",
    "selected_issue_resolution",
    "quality_gate_remediation",
    "understanding_evidence",
    "product_inputs",
)


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _bounded_text(text: str, cap_bytes: int) -> tuple[str, bool]:
    if _byte_len(text) <= cap_bytes:
        return text, False
    encoded = text.encode("utf-8")[: max(cap_bytes - 128, 0)]
    trimmed = encoded.decode("utf-8", errors="ignore")
    return trimmed + "\n[context truncated by Echelon context budget]\n", True


def _phase_matches(value: object, pattern: str) -> bool:
    phase = str(value or "")
    return fnmatch.fnmatchcase(phase, pattern)


def _entry_matches(entry: dict[str, Any], filters: Mapping[str, str]) -> bool:
    requested_type = filters.get("type")
    if requested_type == "routing_decision":
        requested_type = "decision"
    if requested_type and entry.get("type") != requested_type:
        return False
    phase = filters.get("phase")
    if phase and not _phase_matches(entry.get("phase"), phase):
        return False
    return True


def render_journal(path: Path, filters: Mapping[str, str], cap_bytes: int) -> RenderedSection:
    resolved = path.resolve()
    malformed = 0
    entries: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
    except OSError:
        text = f"\n---\n# {resolved}\n[Journal unavailable]"
        return RenderedSection(str(resolved), text, _byte_len(text), {"matched": 0, "included": 0, "malformed": malformed})

    selected = [entry for entry in entries if _entry_matches(entry, filters)]
    rendered: list[str] = []
    used = 0
    for entry in reversed(selected):
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        line_bytes = _byte_len(line) + 1
        if line_bytes > cap_bytes:
            continue
        if rendered and used + line_bytes > cap_bytes:
            break
        rendered.append(line)
        used += line_bytes
    rendered.reverse()
    selector = ", ".join(f"{key}={value}" for key, value in sorted(filters.items()))
    header = (
        f"\n---\n# {resolved}\n"
        f"[Journal context: {len(rendered)}/{len(selected)} matching entries"
        f"{f'; {selector}' if selector else ''}; newest entries retained; malformed={malformed}]"
    )
    text = header + ("\n" + "\n".join(rendered) if rendered else "\n[No matching entries]")
    return RenderedSection(
        str(resolved),
        text,
        _byte_len(text),
        {"matched": len(selected), "included": len(rendered), "malformed": malformed},
    )


def compact_state_projection(
    state: Mapping[str, object],
    phase_id: str,
    allowed_state_updates: object = None,
) -> dict[str, object]:
    projection = {key: state[key] for key in STATE_ALWAYS_KEYS if key in state}
    ledger = state.get("issue_resolution_ledger")
    if isinstance(ledger, dict):
        projection["issue_resolution_statuses"] = {
            str(issue_id): str(entry.get("status") or "unknown")
            for issue_id, entry in ledger.items()
            if isinstance(entry, dict)
        }
    quality_scores = state.get("quality_scores")
    if isinstance(quality_scores, list):
        projection["quality_scores_summary"] = {
            "count": len(quality_scores),
            "latest": quality_scores[-1] if quality_scores else None,
        }
    if allowed_state_updates is not None:
        projection["allowed_state_updates"] = sorted(str(key) for key in allowed_state_updates)
    return projection


def _render_file(path_ref: str, candidate: Path, policy: ContextPolicy) -> RenderedSection:
    resolved = candidate.resolve()
    try:
        raw = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = f"\n---\n# {resolved}\n[File unavailable]"
        return RenderedSection(str(resolved), text, _byte_len(text), {"unavailable": "true"})
    bounded, truncated = _bounded_text(raw, policy.cap_bytes)
    text = f"\n---\n# {resolved}\n{bounded}"
    return RenderedSection(str(resolved), text, _byte_len(text), {"truncated": str(truncated).lower()})


def _directory_manifest(candidate: Path) -> list[Path]:
    return sorted(path for path in candidate.rglob("*") if path.is_file())


def _render_directory(path_ref: str, candidate: Path, policy: ContextPolicy) -> RenderedSection:
    resolved = candidate.resolve()
    files = _directory_manifest(candidate)
    manifest_lines = ["\n---", f"# {resolved.as_posix().rstrip('/')}/", "## Directory manifest"]
    manifest_lines.extend(f"- {path.relative_to(candidate).as_posix()}" for path in files)
    chunks = ["\n".join(manifest_lines)]
    used = _byte_len(chunks[0])
    included = 0
    for path in files:
        rel = path.relative_to(candidate).as_posix()
        body = path.read_text(encoding="utf-8", errors="replace")
        entry = f"\n## {resolved.as_posix().rstrip('/')}/{rel}\n{body}"
        entry_bytes = _byte_len(entry)
        if used + entry_bytes > policy.cap_bytes:
            break
        chunks.append(entry)
        used += entry_bytes
        included += 1
    truncated = included < len(files)
    if truncated:
        chunks.append(f"\n[Directory bodies truncated: included {included}/{len(files)} files]")
    text = "\n".join(chunks)
    return RenderedSection(
        str(resolved),
        text,
        _byte_len(text),
        {"files": len(files), "included_files": included, "truncated": str(truncated).lower()},
    )


def render_context_path(
    path_ref: str,
    candidate: Path,
    policy: ContextPolicy,
    filters: Mapping[str, str],
    state: Mapping[str, object] | None = None,
    phase_id: str = "",
) -> RenderedSection:
    if candidate.name == "reasoning-journal.jsonl":
        return render_journal(candidate, filters, policy.cap_bytes)
    if candidate.name == "state.json" and state is not None:
        text = json.dumps(compact_state_projection(state, phase_id), indent=2, sort_keys=True)
        rendered = f"\n---\n# Current controller state (compact projection)\n{text}"
        return RenderedSection(str(candidate.resolve()), rendered, _byte_len(rendered), {"projection": "compact"})
    if candidate.is_dir():
        return _render_directory(path_ref, candidate, policy)
    return _render_file(path_ref, candidate, policy)
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `PYTHONPATH=src pytest tests/unit/test_agent_context.py -v`

Expected: all Task 1 and Task 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/agent_context.py tests/unit/test_agent_context.py
git commit -m "feat: render bounded agent context"
```

---

### Task 3: Context Budget Report Telemetry

**Files:**
- Modify: `src/harness/agent_context.py`
- Test: `tests/unit/test_agent_context.py`

**Interfaces:**
- Produces:
  - `PromptRenderReport`
  - `build_context_budget_report(...) -> dict[str, object]`
  - `write_context_budget_report(squad_dir: Path, report: Mapping[str, object]) -> Path`

- [ ] **Step 1: Write failing telemetry tests**

Append to `tests/unit/test_agent_context.py`:

```python
from harness.agent_context import (
    RenderedSection,
    build_context_budget_report,
    write_context_budget_report,
)


def test_build_context_budget_report_compares_legacy_and_bounded() -> None:
    report = build_context_budget_report(
        phase_id="phase1-why2",
        agent_id="speckit-echelon-sage",
        mode="WHY2",
        selected_render_mode="bounded",
        legacy_sections=[
            RenderedSection("state.json", "x" * 1000, 1000, {}),
            RenderedSection("reasoning-journal.jsonl", "x" * 3000, 3000, {}),
        ],
        bounded_sections=[
            RenderedSection("state.json", "x" * 200, 200, {"projection": "compact"}),
            RenderedSection("reasoning-journal.jsonl", "x" * 500, 500, {"included": 2}),
        ],
        strict=False,
    )

    assert report["phase"] == "phase1-why2"
    assert report["selected_render_mode"] == "bounded"
    assert report["legacy"]["bytes"] == 4000
    assert report["bounded"]["bytes"] == 700
    assert report["savings"]["bytes"] == 3300
    assert report["savings"]["reduction_pct"] == 82


def test_write_context_budget_report_persists_json(tmp_path: Path) -> None:
    path = write_context_budget_report(
        tmp_path,
        {
            "phase": "phase1-why2",
            "agent": "speckit-echelon-sage",
            "mode": "WHY2",
            "selected_render_mode": "bounded",
            "legacy": {"bytes": 10, "approx_tokens": 3, "top_sections": []},
            "bounded": {"bytes": 5, "approx_tokens": 2, "top_sections": []},
            "savings": {"bytes": 5, "approx_tokens": 1, "reduction_pct": 50},
        },
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.parent == tmp_path / "context-budget"
    assert payload["phase"] == "phase1-why2"
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `PYTHONPATH=src pytest tests/unit/test_agent_context.py -v`

Expected: missing telemetry functions.

- [ ] **Step 3: Implement telemetry functions**

Extend `src/harness/agent_context.py`:

```python
from datetime import datetime, timezone


def _approx_tokens(byte_count: int) -> int:
    return max(1, round(byte_count / 4))


def _section_summary(sections: list[RenderedSection]) -> dict[str, object]:
    total = sum(section.bytes for section in sections)
    top_sections = sorted(
        ({"name": section.title, "bytes": section.bytes, "omitted": section.omitted} for section in sections),
        key=lambda item: int(item["bytes"]),
        reverse=True,
    )[:10]
    return {"bytes": total, "approx_tokens": _approx_tokens(total), "top_sections": top_sections}


def build_context_budget_report(
    *,
    phase_id: str,
    agent_id: str,
    mode: str,
    selected_render_mode: str,
    legacy_sections: list[RenderedSection],
    bounded_sections: list[RenderedSection],
    strict: bool,
) -> dict[str, object]:
    legacy = _section_summary(legacy_sections)
    bounded = _section_summary(bounded_sections)
    legacy_bytes = int(legacy["bytes"])
    bounded_bytes = int(bounded["bytes"])
    saved_bytes = max(0, legacy_bytes - bounded_bytes)
    saved_tokens = max(0, int(legacy["approx_tokens"]) - int(bounded["approx_tokens"]))
    reduction_pct = round((saved_bytes / legacy_bytes) * 100) if legacy_bytes else 0
    return {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": phase_id,
        "agent": agent_id,
        "mode": mode,
        "selected_render_mode": selected_render_mode,
        "strict": strict,
        "legacy": legacy,
        "bounded": bounded,
        "savings": {
            "bytes": saved_bytes,
            "approx_tokens": saved_tokens,
            "reduction_pct": reduction_pct,
        },
    }


def write_context_budget_report(squad_dir: Path, report: Mapping[str, object]) -> Path:
    out_dir = squad_dir / "context-budget"
    out_dir.mkdir(parents=True, exist_ok=True)
    phase = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(report.get("phase") or "unknown"))
    agent = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(report.get("agent") or "agent"))
    existing = len(list(out_dir.glob("dispatch-*.json"))) + 1
    path = out_dir / f"dispatch-{existing:04d}-{phase}-{agent}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `PYTHONPATH=src pytest tests/unit/test_agent_context.py -v`

Expected: all agent context tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/agent_context.py tests/unit/test_agent_context.py
git commit -m "feat: report agent context budget savings"
```

---

### Task 4: Route Normal Agent Prompts Through the Renderer

**Files:**
- Modify: `src/harness/squad_executors.py`
- Test: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Consumes:
  - `parse_context_pack_item`
  - `policy_for_context`
  - `render_context_path`
  - `compact_state_projection`
  - `build_context_budget_report`
  - `write_context_budget_report`
- Produces: normal `_assemble_prompt` no longer injects raw full `state.json` in bounded mode.

- [ ] **Step 1: Write failing normal prompt regression tests**

Add near existing `_assemble_prompt` tests in `tests/kernel/test_squad_executors_journal.py`:

```python
def test_assemble_prompt_bounded_journal_applies_declared_filter(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    (squad_dir / "reasoning-journal.jsonl").write_text(
        json.dumps({"type": "decision", "phase": "phase1-what", "data": {"keep": True}}) + "\n"
        + json.dumps({"type": "decision", "phase": "phase1-old", "data": {"drop": True}}) + "\n",
        encoding="utf-8",
    )
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(
            id="phase1-why2",
            type="agent",
            context_pack=[
                ".specify/squad/reasoning-journal.jsonl [type=routing_decision, phase=phase1-what]"
            ],
        ),
        {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")},
    )

    assert '"keep": true' in prompt
    assert "phase1-old" not in prompt


def test_assemble_prompt_bounded_state_omits_large_raw_ledger(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    (squad_dir / "state.json").write_text(
        json.dumps({"phase": "phase1-why2", "token_ledger": {"raw": "X" * 20_000}}),
        encoding="utf-8",
    )
    ex = _executor(tmp_path, squad_dir=squad_dir)
    from harness.phase_graph import PhaseNode

    prompt = ex._assemble_prompt(
        PhaseNode(id="phase1-why2", type="agent"),
        {
            "squad_dir": str(squad_dir),
            "staging_dir": str(squad_dir / "staging"),
            "phase": "phase1-why2",
        },
    )

    assert "Current controller state (compact projection)" in prompt
    assert "X" * 1000 not in prompt
```

- [ ] **Step 2: Run the target tests**

Run:

```bash
PYTHONPATH=src pytest \
  tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_bounded_journal_applies_declared_filter \
  tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_bounded_state_omits_large_raw_ledger \
  -v
```

Expected: current partial code may pass the journal test for exact phases but the state test should fail for non-WHY nodes if added broadly. If both pass because of existing local partials, continue with the refactor and preserve behavior.

- [ ] **Step 3: Replace local rendering helpers with agent_context imports**

Modify imports in `src/harness/squad_executors.py`:

```python
from harness.agent_context import (
    build_context_budget_report,
    compact_state_projection,
    parse_context_pack_item,
    policy_for_context,
    render_context_path,
    resolve_context_render_mode,
    write_context_budget_report,
)
```

Remove local `_JOURNAL_CONTEXT_MAX_BYTES`, `_WHY_STATE_CONTEXT_KEYS`, `_context_pack_filters`, `_render_reasoning_journal_context`, and `_render_why_state_context` after their callers are updated.

- [ ] **Step 4: Add a local context rendering method to `PhaseExecutor`**

Add inside `PhaseExecutor`:

```python
    def _render_context_pack_item(
        self,
        *,
        item: str,
        node_id: str,
        agent_id: str,
        mode: str,
        state: dict,
        search_bases: list[Path],
        translate_ref,
    ):
        selector = parse_context_pack_item(item)
        if not selector.path_ref or selector.path_ref.startswith("#"):
            return None
        resolved = translate_ref(selector.path_ref)
        candidates = [Path(resolved)] if resolved.startswith("/") else [base / resolved for base in search_bases]
        for candidate in candidates:
            if candidate.exists():
                policy = policy_for_context(
                    phase_id=node_id,
                    agent_id=agent_id,
                    mode=mode,
                    path_ref=selector.path_ref,
                )
                return render_context_path(
                    selector.path_ref,
                    candidate,
                    policy,
                    selector.filters,
                    state=state,
                    phase_id=node_id,
                )
        return None
```

Use the returned `RenderedSection.text` for prompt content. Keep a `bounded_sections` list for telemetry.

- [ ] **Step 5: Render compact state for all bounded normal prompts**

In `_assemble_prompt`, replace:

```python
state_path = self._squad_dir / "state.json"
if node.id in {"phase1-why1", "phase1-why2"}:
    dynamic_parts.append(_render_why_state_context(state))
elif state_path.exists():
    dynamic_parts.append(f"\n---\n# Current state.json\n{state_path.read_text()}")
```

with:

```python
state_projection = compact_state_projection(
    state,
    node.id,
    getattr(node, "allowed_state_updates", None),
)
state_text = json.dumps(state_projection, indent=2, ensure_ascii=False, sort_keys=True)
dynamic_parts.append("\n---\n# Current controller state (compact projection)\n" + state_text)
```

For legacy mode, keep the old raw state behavior in the locally measured legacy prompt, not in the selected bounded prompt.

- [ ] **Step 6: Write telemetry after prompt assembly**

After bounded and legacy sections exist, call:

```python
report = build_context_budget_report(
    phase_id=node.id,
    agent_id=str(node.agent or ""),
    mode=str(getattr(node, "mode", "") or node.id),
    selected_render_mode=resolve_context_render_mode(),
    legacy_sections=legacy_sections,
    bounded_sections=bounded_sections,
    strict=False,
)
report_path = write_context_budget_report(self._squad_dir, report)
if report["bounded"]["bytes"] < report["legacy"]["bytes"]:
    print(f"[squad] context bounded for {node.id}; report={report_path}", flush=True)
```

If assembling complete legacy sections is too intrusive in this task, use one legacy section containing the final legacy prompt text and split bounded sections normally. Do not store full prompts in the report.

- [ ] **Step 7: Run focused executor tests**

Run:

```bash
PYTHONPATH=src pytest \
  tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_bounded_journal_applies_declared_filter \
  tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_bounded_state_omits_large_raw_ledger \
  tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_injects_squad_context \
  tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_injects_resolved_project_quality_gates \
  -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/harness/squad_executors.py tests/kernel/test_squad_executors_journal.py
git commit -m "feat: bound normal squad agent context"
```

---

### Task 5: Route Staged Parallel Prompts Through the Renderer

**Files:**
- Modify: `src/harness/squad_executors.py`
- Test: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Consumes: Task 4 renderer method.
- Produces: `_build_agent_prompt` applies the same bounded directory/journal logic as normal prompts.

- [ ] **Step 1: Write failing staged prompt regression tests**

Add near existing staged prompt tests:

```python
def test_staged_prompt_bounded_contracts_preserves_manifest(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    staging_dir = squad_dir / "staging"
    staging_dir.mkdir(parents=True)
    ext_dir = tmp_path / "ext"
    agent_dir = ext_dir / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "sage.md").write_text("# SAGE\nRole-specific instructions.", encoding="utf-8")
    spec_dir = tmp_path / "specs" / "001-demo"
    contracts = spec_dir / "contracts"
    contracts.mkdir(parents=True)
    (contracts / "a.md").write_text("# A\n" + "a" * 100_000, encoding="utf-8")
    (contracts / "b.md").write_text("# B\n" + "b" * 100_000, encoding="utf-8")

    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = "agents/sage.md"
    graph.all_phase_ids.return_value = []
    ex = StagedParallelExecutor(provider, graph, ext_dir, tmp_path, squad_dir)

    prompt = ex._build_agent_prompt(
        {"id": "speckit-echelon-sage", "mode": "WHY3", "context_pack": ["{spec_dir}/contracts/"]},
        {
            "squad_dir": str(squad_dir),
            "staging_dir": str(staging_dir),
            "spec_dir": "specs/001-demo",
        },
    )

    assert "## Directory manifest" in prompt
    assert "a.md" in prompt
    assert "b.md" in prompt
    assert len(prompt.encode("utf-8")) < 180_000
```

- [ ] **Step 2: Run the staged test to verify failure or current unbounded behavior**

Run:

```bash
PYTHONPATH=src pytest \
  tests/kernel/test_squad_executors_journal.py::test_staged_prompt_bounded_contracts_preserves_manifest \
  -v
```

Expected before implementation: prompt includes the full directory bodies and exceeds the expected byte guard.

- [ ] **Step 3: Update `_build_agent_prompt` context-pack loop**

Replace its per-agent context loop with the shared `_render_context_pack_item` method. Use:

```python
rendered = self._render_context_pack_item(
    item=item,
    node_id="phase3-consensus",
    agent_id=agent_id,
    mode=mode_label,
    state=state,
    search_bases=search_bases,
    translate_ref=lambda ref: (
        ref.replace("{spec_dir}", spec_dir_ref)
        .replace("{context_dir}", context_dir_str)
        .replace("{staging_dir}", staging_dir_str)
    ),
)
if rendered is not None:
    dynamic_parts.append(rendered.text)
    bounded_sections.append(rendered)
```

Add compact state projection to staged prompts only if needed for telemetry or if the staged agent contract already needs state. Do not add new raw state context.

- [ ] **Step 4: Write staged context budget report**

Use the same report writer as Task 4 with:

```python
phase_id="phase3-consensus"
agent_id=agent_id
mode=mode_label
```

Print a warning only when bounded sections omitted content.

- [ ] **Step 5: Run staged and normal focused tests**

Run:

```bash
PYTHONPATH=src pytest \
  tests/kernel/test_squad_executors_journal.py::test_staged_prompt_bounded_contracts_preserves_manifest \
  tests/kernel/test_squad_executors_journal.py::test_staged_prompt_includes_directory_context_pack_contents \
  tests/kernel/test_squad_executors_journal.py::test_assemble_prompt_bounded_journal_applies_declared_filter \
  -v
```

Expected: all pass. Existing directory test should still see the contract content for small directories.

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad_executors.py tests/kernel/test_squad_executors_journal.py
git commit -m "feat: bound staged squad agent context"
```

---

### Task 6: Benchmark Context Render Option

**Files:**
- Modify: `src/echelon/benchmark.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_benchmark.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Produces:
  - `ContextRenderMode = Literal["legacy", "bounded", "both"]` or equivalent validation helper.
  - `run_benchmark_variant(..., context_render: str = "bounded") -> Path`
  - Benchmark records with `context_render` and render-qualified `variant_id` for `both`.

- [ ] **Step 1: Write failing benchmark tests**

Add to `tests/unit/test_benchmark.py`:

```python
def test_benchmark_dry_run_includes_context_render_env(tmp_path: Path, capsys) -> None:
    _cmd_benchmark(
        [
            "run",
            "tiny-notes",
            "--variant",
            "baseline",
            "--baseline-ref",
            "baseline-artifacts",
            "--context-render",
            "bounded",
            "--dry-run",
        ],
        project_root=tmp_path,
    )

    out = capsys.readouterr().out
    assert "ECHELON_CONTEXT_RENDER_MODE=bounded echelon spec run --mode banzai" in out


def test_benchmark_rejects_unknown_context_render(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_benchmark(
            ["run", "tiny-notes", "--variant", "baseline", "--context-render", "bad"],
            project_root=tmp_path,
        )

    assert exc.value.code == 1
    assert "Unknown context render mode" in capsys.readouterr().err


def test_benchmark_run_passes_context_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_benchmark_variant(
        project_root: Path,
        fixture_id: str,
        variant_id: str,
        *,
        baseline_ref: str | None = None,
        artifact_only: bool = False,
        context_render: str = "bounded",
    ) -> Path:
        calls.append({"context_render": context_render, "variant_id": variant_id})
        output_dir = tmp_path / "runs" / "benchmarks" / "fake" / variant_id
        output_dir.mkdir(parents=True)
        return output_dir

    monkeypatch.setattr("echelon.benchmark.run_benchmark_variant", fake_run_benchmark_variant)

    _cmd_benchmark(
        ["run", "tiny-notes", "--variant", "baseline", "--context-render", "legacy"],
        project_root=tmp_path,
    )

    assert calls == [{"context_render": "legacy", "variant_id": "baseline"}]
```

- [ ] **Step 2: Run benchmark tests to verify failure**

Run:

```bash
PYTHONPATH=src pytest \
  tests/unit/test_benchmark.py::test_benchmark_dry_run_includes_context_render_env \
  tests/unit/test_benchmark.py::test_benchmark_rejects_unknown_context_render \
  tests/unit/test_benchmark.py::test_benchmark_run_passes_context_render \
  -v
```

Expected: unknown argument or missing parameter failures.

- [ ] **Step 3: Add environment-aware benchmark command execution**

In `src/echelon/benchmark.py`, keep the existing command tuple shape for compatibility with tests and injected runners:

```python
CommandRunner = Callable[[tuple[str, ...]], int]
CONTEXT_RENDER_MODES = {"legacy", "bounded", "both"}
```

Add:

```python
def _format_context_command(command: tuple[str, ...], context_render: str) -> str:
    if command and command[0] == "git":
        return " ".join(command)
    return f"ECHELON_CONTEXT_RENDER_MODE={context_render} " + " ".join(command)
```

For actual execution, keep `CommandRunner` unchanged and set the process environment around non-git runner calls:

```python
def _run_with_context(
    run: CommandRunner,
    command: tuple[str, ...],
    context_render: str,
) -> int:
    if command and command[0] == "git":
        return run(command)
    previous = os.environ.get("ECHELON_CONTEXT_RENDER_MODE")
    os.environ["ECHELON_CONTEXT_RENDER_MODE"] = context_render
    try:
        return run(command)
    finally:
        if previous is None:
            os.environ.pop("ECHELON_CONTEXT_RENDER_MODE", None)
        else:
            os.environ["ECHELON_CONTEXT_RENDER_MODE"] = previous
```

This preserves existing runner injection while making the selected render mode visible to child `echelon` commands.

- [ ] **Step 4: Add context_render to planning and execution**

Update signatures:

```python
def variant_execution_commands(
    plan: BenchmarkCommandPlan,
    baseline_ref: str,
    *,
    context_render: str = "bounded",
) -> tuple[tuple[str, ...], ...]:
```

Keep this function returning executable command tuples. In dry-run printing, use `_format_context_command(command, context_render)` so users see the environment prefix without changing what the runner receives.

Update `run_benchmark_variant(..., context_render: str = "bounded")`.

Validate:

```python
if context_render not in CONTEXT_RENDER_MODES:
    raise ValueError(f"Unknown context render mode: {context_render}")
```

For `both`, run two internal passes with render modes `legacy` and `bounded`, using the same `resolved_baseline_ref`. Records should use `variant_id=f"{variant_id}:{render_mode}"` and include `context_render=render_mode`.

- [ ] **Step 5: Extend `BenchmarkRunRecord`**

Add fields:

```python
context_render: str = "bounded"
base_variant_id: str = ""
context_prompt_bytes: int = 0
context_prompt_tokens_estimate: int = 0
context_reduction_pct: int = 0
```

When collecting records, scan current run context budget reports:

```python
def _context_budget_totals(squad_dir: Path) -> dict[str, int]:
    totals = {"bytes": 0, "approx_tokens": 0, "reduction_pct": 0}
    reports = sorted((squad_dir / "context-budget").glob("dispatch-*.json"))
    reductions = []
    for report in reports:
        payload = json.loads(report.read_text(encoding="utf-8"))
        selected = str(payload.get("selected_render_mode") or "bounded")
        selected_payload = payload.get(selected)
        if isinstance(selected_payload, dict):
            totals["bytes"] += int(selected_payload.get("bytes") or 0)
            totals["approx_tokens"] += int(selected_payload.get("approx_tokens") or 0)
        savings = payload.get("savings")
        if isinstance(savings, dict):
            reductions.append(int(savings.get("reduction_pct") or 0))
    totals["reduction_pct"] = round(sum(reductions) / len(reductions)) if reductions else 0
    return totals
```

- [ ] **Step 6: Update CLI parsing**

In `src/echelon/cli.py`, extend usage text and parse:

```python
context_render = "bounded"
...
elif args[i] == "--context-render" and i + 1 < len(args):
    context_render = args[i + 1]
    i += 2
```

Validate before planning:

```python
if context_render not in {"legacy", "bounded", "both"}:
    print(f"✗ Unknown context render mode: {context_render}", file=sys.stderr)
    sys.exit(1)
```

Pass `context_render=context_render` into `run_benchmark_variant` and dry-run command generation.

In `src/echelon/cli_app.py`, add:

```python
context_render: str = typer.Option(
    "bounded",
    "--context-render",
    help="Context render mode: bounded, legacy, or both.",
),
```

Append `--context-render` to legacy args.

- [ ] **Step 7: Run benchmark tests**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_benchmark.py tests/unit/test_cli_typer_app.py::test_benchmark_help_declares_run_and_show_contracts -v
```

Expected: all pass after updating expected help strings if needed.

- [ ] **Step 8: Commit**

```bash
git add src/echelon/benchmark.py src/echelon/cli.py src/echelon/cli_app.py tests/unit/test_benchmark.py tests/unit/test_cli_typer_app.py
git commit -m "feat: benchmark context render modes"
```

---

### Task 7: End-to-End Regression and Documentation Check

**Files:**
- Modify: `docs/superpowers/specs/2026-07-30-agent-context-budgeting-design.md` only if implementation discovers a design mismatch.
- Test: existing test suites.

**Interfaces:**
- Consumes all previous tasks.
- Produces verified behavior and a clean final state.

- [ ] **Step 1: Run focused context tests**

Run:

```bash
PYTHONPATH=src pytest \
  tests/unit/test_agent_context.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_benchmark.py \
  -v
```

Expected: all pass.

- [ ] **Step 2: Run relevant broader suites**

Run:

```bash
PYTHONPATH=src pytest tests/unit/test_cli_typer_app.py tests/kernel/test_phase_graph.py -v
```

Expected: all pass. If unrelated failures occur, capture exact failing test names and do not hide them.

- [ ] **Step 3: Run a dry-run benchmark comparison command**

Run:

```bash
PYTHONPATH=src python -m echelon.cli benchmark run tiny-notes --variant baseline --context-render both --baseline-ref HEAD --dry-run
```

Expected output contains:

```text
ECHELON_CONTEXT_RENDER_MODE=legacy echelon spec run --mode banzai
ECHELON_CONTEXT_RENDER_MODE=bounded echelon spec run --mode banzai
```

- [ ] **Step 4: Inspect generated context budget report shape from a unit fixture**

Run:

```bash
PYTHONPATH=src python - <<'PY'
from pathlib import Path
import json
from harness.agent_context import RenderedSection, build_context_budget_report, write_context_budget_report
root = Path('/tmp/echelon-context-budget-smoke')
report = build_context_budget_report(
    phase_id='phase1-why2',
    agent_id='speckit-echelon-sage',
    mode='WHY2',
    selected_render_mode='bounded',
    legacy_sections=[RenderedSection('legacy', 'x' * 100, 100, {})],
    bounded_sections=[RenderedSection('bounded', 'x' * 20, 20, {})],
    strict=False,
)
path = write_context_budget_report(root, report)
print(path)
print(json.loads(path.read_text())['savings']['reduction_pct'])
PY
```

Expected: prints a `/tmp/echelon-context-budget-smoke/context-budget/dispatch-...json` path and `80`.

- [ ] **Step 5: Check git status**

Run: `git status --short`

Expected: only intentional files modified. Existing unrelated files such as `knowledge-base/.locks/` may remain untracked and must not be added.

- [ ] **Step 6: Commit final verification adjustments if any**

If Step 1-4 required any fixes:

```bash
git add <changed-files>
git commit -m "test: verify agent context budgeting"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Warn-and-truncate default: Task 3 report and Task 4/5 selected bounded dispatch.
- Dual local measurement: Task 3 and Task 4 report construction.
- Phase-aware truncation: Task 1 policy table and Task 2 path-aware rendering.
- Journal filtering: Task 2 and Task 4 tests.
- Compact state: Task 2 and Task 4 tests.
- Directory bounding: Task 2 and Task 5 tests.
- Benchmark `legacy|bounded|both`: Task 6.
- Avoid destabilizing flow: Tasks 4 and 5 preserve existing prompt assembly structure and use focused regression tests.

Red-flag scan: no vague task steps remain. All code snippets define concrete functions and tests.

Type consistency:

- `ContextSelector`, `ContextPolicy`, and `RenderedSection` are defined before use.
- `render_context_path` consumes `ContextPolicy` and returns `RenderedSection`.
- Benchmark records use `context_render` and `base_variant_id` consistently.
