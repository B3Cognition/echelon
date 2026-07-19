# Echelon Human Wiki Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline `echelon wiki` command group that builds, inspects, cleans, and safely auto-refreshes a local human-navigation vault from canonical `specs/` and `re/` artifacts.

**Architecture:** A focused `echelon.wiki` package separates immutable data models, canonical discovery, Markdown rendering, and atomic lifecycle operations. The Typer front door exposes `build`, `status`, and `clean`; its outer `run()` wrapper captures canonical input hashes before and after successful commands so an existing vault refreshes only when that command changed wiki inputs.

**Tech Stack:** Python 3.11, standard library (`dataclasses`, `hashlib`, `json`, `pathlib`, `shutil`, `subprocess`, `tempfile`), PyYAML through the existing config stack, Typer, pytest.

## Global Constraints

- Canonical inputs are the safe subset of Echelon's resolved config plus published `specs/` and `re/` artifacts.
- `.echelon/local.yml` overrides `.echelon/config.yml`; the wiki never serializes unrestricted resolved config.
- Output is fixed at `.echelon/runtime/wiki/`, remains untracked, and is replaceable only when it carries a valid Echelon wiki manifest.
- Generation is deterministic for identical inputs and a fixed clock, offline, and invokes no LLM.
- Standard Markdown links are required; Obsidian is an optional viewer and is never installed or launched.
- Existing artifact frontmatter and fenced code are preserved in projected copies.
- Non-text attachments larger than 10 MiB are catalogued instead of copied.
- A failed build preserves the previous valid vault.
- Auto-refresh is opt-in through the existence of a valid vault and runs only after a successful command changes canonical input hashes.
- The reference benchmark is 100 specs, 2,000 artifacts, and 50 MiB of Markdown in at most 5 seconds with peak RSS below 512 MiB.

---

## File structure

- `src/echelon/wiki/__init__.py`: public wiki service exports.
- `src/echelon/wiki/model.py`: immutable nodes, relationships, warnings, and build/status result types.
- `src/echelon/wiki/discovery.py`: safe config extraction, canonical input enumeration, hashing, spec/RE parsing, and `WikiModel` construction.
- `src/echelon/wiki/render.py`: Markdown page generation, artifact projection, viewer config, and link validation.
- `src/echelon/wiki/service.py`: manifest persistence, Git provenance, atomic publication, status, clean, snapshots, and best-effort refresh.
- `src/echelon/cli_app.py`: Typer command group and before/after successful-command refresh hook.
- `tests/unit/test_wiki_discovery.py`: config, discovery, identity, relationship, and containment tests.
- `tests/unit/test_wiki_render.py`: golden navigation, projection, link, and attachment tests.
- `tests/unit/test_wiki_service.py`: atomic build, freshness, clean, and failure preservation tests.
- `tests/unit/test_cli_wiki.py`: CLI routing, output, and auto-refresh semantics.
- `tests/performance/test_wiki_build_performance.py`: marked slow reference benchmark.
- `README.md`: user-facing command and viewing guidance.

### Task 1: Wiki model and canonical discovery

**Files:**
- Create: `src/echelon/wiki/__init__.py`
- Create: `src/echelon/wiki/model.py`
- Create: `src/echelon/wiki/discovery.py`
- Create: `tests/unit/test_wiki_discovery.py`

**Interfaces:**
- Consumes: `harness.config.get_full_resolved_config(Path)`, `harness.spec_frontmatter.read_frontmatter(Path)`.
- Produces: `WikiModel`, `WikiArtifact`, `WikiSpec`, `WikiSource`, `WikiDomain`, `WikiRelationship`, `WikiRecentChange`, `WikiWarning`, `discover_wiki_model(project_root, generated_at)`, and `canonical_input_hashes(project_root)`.

- [ ] **Step 1: Write failing safe-config and discovery tests**

```python
def test_discovery_uses_local_source_override_without_leaking_secrets(tmp_path):
    write_yaml(tmp_path / ".echelon/config.yml", {
        "sources": [{"id": "api", "path": "sources/api"}],
        "llm": {"api_key": "committed-secret"},
    })
    write_yaml(tmp_path / ".echelon/local.yml", {
        "sources": [{"id": "web", "path": "sources/web"}],
        "deploy": {"token": "local-secret"},
    })
    write_spec(tmp_path / "specs/001-demo", status="phase_a")

    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")

    assert [(source.source_id, source.path) for source in model.sources] == [
        ("web", "sources/web")
    ]
    serialized = repr(model)
    assert "committed-secret" not in serialized
    assert "local-secret" not in serialized


def test_discovery_namespaces_ids_and_records_explicit_target_relationship(tmp_path):
    write_yaml(tmp_path / ".echelon/config.yml", {
        "sources": [{"id": "api", "path": "sources/api"}],
    })
    spec = write_spec(tmp_path / "specs/001-demo", status="ready_to_land")
    write_yaml(spec / "targets.yml", {"targets": ["api"]})
    (spec / "tasks.md").write_text("# Tasks\n\n- [ ] T-001 Build API\n")

    model = discover_wiki_model(tmp_path, generated_at="2026-07-18T10:00:00Z")

    assert model.specs[0].stable_id == "spec:001-demo"
    assert model.specs[0].task_ids == ("001-demo:T-001",)
    assert any(
        edge.kind == "targets"
        and edge.source_id == "spec:001-demo"
        and edge.target_id == "source:api"
        for edge in model.relationships
    )
```

- [ ] **Step 2: Run the discovery tests and confirm the missing package failure**

Run: `pytest tests/unit/test_wiki_discovery.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'echelon.wiki'`.

- [ ] **Step 3: Implement immutable model types**

Create frozen dataclasses with these exact public fields:

```python
@dataclass(frozen=True)
class WikiWarning:
    code: str
    message: str
    source_path: str | None = None


@dataclass(frozen=True)
class WikiArtifact:
    stable_id: str
    source_path: str
    projection_path: str
    title: str
    kind: str
    sha256: str
    size_bytes: int
    copy_mode: str


@dataclass(frozen=True)
class WikiSpec:
    stable_id: str
    spec_id: str
    source_path: str
    title: str
    lifecycle_status: str
    targets: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]


@dataclass(frozen=True)
class WikiSource:
    stable_id: str
    source_id: str
    path: str
    published_path: str | None


@dataclass(frozen=True)
class WikiDomain:
    stable_id: str
    source_id: str
    domain_id: str
    source_path: str
    title: str


@dataclass(frozen=True)
class WikiRelationship:
    kind: str
    source_id: str
    target_id: str
    evidence_path: str
    evidence_key: str


@dataclass(frozen=True)
class WikiRecentChange:
    commit: str
    committed_at: str
    subject: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class WikiModel:
    schema_version: int
    generated_at: str
    workspace_name: str
    workspace_root: str
    sources: tuple[WikiSource, ...]
    domains: tuple[WikiDomain, ...]
    specs: tuple[WikiSpec, ...]
    artifacts: tuple[WikiArtifact, ...]
    relationships: tuple[WikiRelationship, ...]
    recent_changes: tuple[WikiRecentChange, ...]
    warnings: tuple[WikiWarning, ...]
```

- [ ] **Step 4: Implement safe canonical discovery**

Implement:

```python
def canonical_input_hashes(project_root: Path) -> dict[str, str]:
    """Hash safe config identity plus allowed files below specs/ and re/."""


def discover_wiki_model(project_root: Path, *, generated_at: str) -> WikiModel:
    """Build a sorted, evidence-backed model from canonical workspace artifacts."""
```

The implementation must resolve paths before reading, reject symlinks escaping
`specs/` or `re/`, ignore `re/.cache`, `re/.staging`, and `re/.locks`, use SHA-256,
parse H1 titles and spec lifecycle frontmatter, namespace requirement/task IDs by
spec ID, and derive `targets` edges only from `targets.yml` values matching resolved
`sources[].id`. Parse explicit requirement-to-task and requirement-to-verification
rows into evidence-backed relationships. Derive at most ten recent changes from
`git log` limited to `specs/` and `re/`; each record includes only commits that
changed a canonical input. Add a synthetic `WORKTREE` record listing dirty
canonical inputs relative to `HEAD`, and never use filesystem mtimes as history.

- [ ] **Step 5: Run discovery tests**

Run: `pytest tests/unit/test_wiki_discovery.py -q`

Expected: PASS.

- [ ] **Step 6: Commit discovery**

```bash
git add src/echelon/wiki tests/unit/test_wiki_discovery.py
git commit -m "feat: discover human wiki artifacts"
```

### Task 2: Markdown renderer and projection validation

**Files:**
- Create: `src/echelon/wiki/render.py`
- Create: `tests/unit/test_wiki_render.py`

**Interfaces:**
- Consumes: `WikiModel` from Task 1 and canonical files rooted at `project_root`.
- Produces: `render_wiki(model, project_root, output_dir) -> RenderResult` and `validate_rendered_links(output_dir) -> tuple[WikiWarning, ...]`.

- [ ] **Step 1: Write failing golden-layout and projection tests**

```python
def test_render_writes_navigation_views_and_self_contained_projection(tmp_path):
    model, project_root = model_fixture(tmp_path)
    output = tmp_path / "out"

    result = render_wiki(model, project_root, output)

    assert result.required_pages == (
        "Home.md",
        "Reverse Engineering/Index.md",
        "Specs/Index.md",
        "Views/Active Work.md",
        "Views/Decisions.md",
        "Views/Requirements.md",
        "Views/Risks and Issues.md",
        "Views/Verification.md",
        "Warnings.md",
    )
    assert "[001 Demo](Specs/001-demo/Overview.md)" in (output / "Home.md").read_text()
    assert "Recent Changes" in (output / "Home.md").read_text()
    projection = output / "Artifacts/specs/001-demo/spec.md"
    assert "Canonical source: `specs/001-demo/spec.md`" in projection.read_text()
    assert (output / ".obsidian/app.json").is_file()


def test_projection_preserves_frontmatter_and_fenced_code(tmp_path):
    source = write_artifact(
        tmp_path,
        "specs/001-demo/spec.md",
        "---\nstatus: phase_a\n---\n# Spec\n```md\n[not a link](missing.md)\n```\n",
    )
    model = discover_fixture_model(tmp_path)

    render_wiki(model, tmp_path, tmp_path / "out")

    rendered = (tmp_path / "out/Artifacts/specs/001-demo/spec.md").read_text()
    assert rendered.startswith("---\nstatus: phase_a\n---\n")
    assert "```md\n[not a link](missing.md)\n```" in rendered
    assert source.read_text().split("```md", 1)[1] in rendered
```

- [ ] **Step 2: Run renderer tests and confirm failure**

Run: `pytest tests/unit/test_wiki_render.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'echelon.wiki.render'`.

- [ ] **Step 3: Implement deterministic navigation rendering**

Implement:

```python
@dataclass(frozen=True)
class RenderResult:
    output_pages: tuple[str, ...]
    required_pages: tuple[str, ...]
    warnings: tuple[WikiWarning, ...]


def render_wiki(model: WikiModel, project_root: Path, output_dir: Path) -> RenderResult:
    """Render sorted standard-Markdown navigation and artifact projections."""
```

Write the approved directory layout, fixed navigation frontmatter keys
(`echelon_wiki`, `page_type`, `stable_id`, `generated_at`), one spec overview per
spec, aggregate views, `Warnings.md`, and `.obsidian/app.json` configured for
relative Markdown links. Use POSIX paths in generated content on every platform.

- [ ] **Step 4: Implement faithful artifact projection and link validation**

Projection must insert a plain Markdown blockquote after existing YAML frontmatter,
preserve fenced regions byte-for-byte, retain the source-relative directory layout,
copy known images and attachments at or below 10 MiB, and catalog larger files.

Implement link validation that ignores external schemes, absolute URLs, anchors,
and Markdown-looking text inside fenced code. Missing required navigation targets
raise `WikiRenderError`; missing optional projection targets return `WikiWarning`.

- [ ] **Step 5: Run renderer tests**

Run: `pytest tests/unit/test_wiki_render.py -q`

Expected: PASS.

- [ ] **Step 6: Commit renderer**

```bash
git add src/echelon/wiki/render.py tests/unit/test_wiki_render.py
git commit -m "feat: render human wiki vault"
```

### Task 3: Atomic build, status, and clean service

**Files:**
- Create: `src/echelon/wiki/service.py`
- Modify: `src/echelon/wiki/__init__.py`
- Create: `tests/unit/test_wiki_service.py`

**Interfaces:**
- Consumes: Task 1 discovery and Task 2 renderer.
- Produces: `build_wiki`, `wiki_status`, `clean_wiki`, `capture_input_snapshot`, and `refresh_after_changed_command`.

- [ ] **Step 1: Write failing service lifecycle tests**

```python
def test_failed_rebuild_preserves_previous_valid_vault(tmp_path, monkeypatch):
    first = build_wiki(tmp_path, now=fixed_now)
    home_before = (first.output_dir / "Home.md").read_bytes()
    monkeypatch.setattr("echelon.wiki.service.render_wiki", raise_render_error)

    with pytest.raises(WikiBuildError):
        build_wiki(tmp_path, now=fixed_now)

    assert (first.output_dir / "Home.md").read_bytes() == home_before
    assert wiki_status(tmp_path).state == "fresh"


def test_status_detects_changed_added_and_removed_inputs(tmp_path):
    build_wiki(tmp_path, now=fixed_now)
    spec = tmp_path / "specs/001-demo/spec.md"
    spec.write_text("# Changed\n")
    (tmp_path / "specs/001-demo/new.md").write_text("# New\n")

    status = wiki_status(tmp_path)

    assert status.state == "stale"
    assert "specs/001-demo/spec.md" in status.changed_inputs
    assert "specs/001-demo/new.md" in status.added_inputs


def test_clean_refuses_output_without_valid_manifest(tmp_path):
    output = tmp_path / ".echelon/runtime/wiki"
    output.mkdir(parents=True)
    (output / "human-note.md").write_text("keep me\n")

    with pytest.raises(WikiCleanError, match="valid Echelon wiki manifest"):
        clean_wiki(tmp_path)

    assert (output / "human-note.md").is_file()
```

- [ ] **Step 2: Run service tests and confirm failure**

Run: `pytest tests/unit/test_wiki_service.py -q`

Expected: FAIL with missing `echelon.wiki.service` imports.

- [ ] **Step 3: Implement manifest and status types**

Expose these result contracts:

```python
@dataclass(frozen=True)
class WikiBuildResult:
    output_dir: Path
    home_path: Path
    input_count: int
    output_count: int
    warning_count: int


@dataclass(frozen=True)
class WikiStatusResult:
    state: Literal["absent", "fresh", "stale", "invalid"]
    output_dir: Path
    workspace_revision: str | None
    workspace_dirty: bool
    added_inputs: tuple[str, ...]
    changed_inputs: tuple[str, ...]
    removed_inputs: tuple[str, ...]
    message: str
```

The manifest contains a fixed marker, schema/generator versions, timestamp, Git
revision and dirty flag, sorted input hashes, output page paths, relationships, and
warnings. JSON is emitted with sorted keys and a trailing newline.

- [ ] **Step 4: Implement atomic build and conservative clean**

`build_wiki()` creates staging below `.echelon/runtime/`, renders and validates,
writes the manifest last, moves a valid old output to a backup, renames staging to
the canonical path, deletes the backup, and rolls back if final rename fails.
`clean_wiki()` validates the marker and schema before `shutil.rmtree()`.

- [ ] **Step 5: Implement snapshot and refresh service**

```python
def capture_input_snapshot(project_root: Path) -> dict[str, str] | None:
    """Return hashes only when a valid wiki already exists; otherwise None."""


def refresh_after_changed_command(
    project_root: Path,
    before: dict[str, str] | None,
) -> WikiBuildResult | None:
    """Rebuild only when before exists, inputs changed, and auto_refresh is enabled."""
```

Read `wiki.auto_refresh` from `get_full_resolved_config`; only literal `False`
disables it. Exceptions are wrapped as warnings by the CLI caller and never alter
the completed primary command.

- [ ] **Step 6: Run service tests**

Run: `pytest tests/unit/test_wiki_service.py -q`

Expected: PASS.

- [ ] **Step 7: Commit service**

```bash
git add src/echelon/wiki tests/unit/test_wiki_service.py
git commit -m "feat: manage human wiki lifecycle"
```

### Task 4: CLI commands and command-boundary auto-refresh

**Files:**
- Modify: `src/echelon/cli_app.py`
- Create: `tests/unit/test_cli_wiki.py`
- Modify: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: Task 3 public service functions.
- Produces: `echelon wiki build`, `echelon wiki status`, `echelon wiki clean`, and successful-command auto-refresh.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_wiki_build_prints_home_and_optional_obsidian_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_minimal_workspace(tmp_path)

    result = CliRunner().invoke(app, ["wiki", "build"])

    assert result.exit_code == 0
    assert ".echelon/runtime/wiki/Home.md" in result.output
    assert "Obsidian" in result.output
    assert "optional" in result.output


def test_read_only_command_does_not_refresh_preexisting_stale_vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_minimal_workspace(tmp_path)
    run(["wiki", "build"])
    (tmp_path / "specs/001-demo/spec.md").write_text("# External change\n")
    before = (tmp_path / ".echelon/runtime/wiki/manifest.json").read_bytes()

    run(["wiki", "status"])

    assert (tmp_path / ".echelon/runtime/wiki/manifest.json").read_bytes() == before


def test_successful_command_that_changes_inputs_refreshes_existing_vault(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    write_minimal_workspace(tmp_path)
    run(["wiki", "build"])
    monkeypatch.setattr("echelon.cli._cmd_artifacts", mutate_canonical_spec)

    run(["spec", "artifacts", "001"])

    assert "changed by command" in (
        tmp_path / ".echelon/runtime/wiki/Artifacts/specs/001-demo/spec.md"
    ).read_text()
```

- [ ] **Step 2: Run CLI tests and confirm missing command failure**

Run: `pytest tests/unit/test_cli_wiki.py tests/unit/test_cli_typer_app.py -q`

Expected: FAIL because `wiki` is not a registered Typer command.

- [ ] **Step 3: Register the Typer wiki command group**

Add `wiki_app = typer.Typer(...)`, `app.add_typer(wiki_app, name="wiki")`, and three
commands. `build` prints counts, `Home.md`, and the optional Obsidian download URL.
`status` prints state plus changed paths and exits nonzero only for `invalid`.
`clean` reports `absent` idempotently and otherwise prints the removed path.

- [ ] **Step 4: Wrap successful CLI execution with input snapshots**

Change `run()` to capture `before = capture_input_snapshot(Path.cwd())` immediately
before invoking Typer. Call `refresh_after_changed_command(Path.cwd(), before)` only
after Typer returns successfully. Print a one-line refreshed message on success and
print `warning: wiki auto-refresh failed: ...` to stderr on failure without raising.

Because before/after hashes must differ, an externally stale vault remains stale
when the user runs a read-only command. Failed commands do not reach the refresh
hook.

- [ ] **Step 5: Run CLI tests**

Run: `pytest tests/unit/test_cli_wiki.py tests/unit/test_cli_typer_app.py -q`

Expected: PASS.

- [ ] **Step 6: Commit CLI integration**

```bash
git add src/echelon/cli_app.py tests/unit/test_cli_wiki.py tests/unit/test_cli_typer_app.py
git commit -m "feat: expose human wiki commands"
```

### Task 5: Documentation, performance gate, and regression verification

**Files:**
- Modify: `README.md`
- Create: `tests/performance/test_wiki_build_performance.py`
- Modify: `docs/superpowers/specs/2026-07-18-echelons-human-wiki-design.md` only if implementation reveals an approved-contract correction.

**Interfaces:**
- Consumes: complete CLI and service.
- Produces: user documentation and measured regression evidence.

- [ ] **Step 1: Add the reference performance test**

Create a `@pytest.mark.slow` test that generates 100 spec folders, 20 Markdown
artifacts per spec, and enough repeated deterministic content to total 50 MiB.
Measure `time.perf_counter()` around `build_wiki()` and `resource.getrusage()` where
available. Assert elapsed time is at most 5 seconds and Linux/macOS peak RSS,
normalized to bytes, remains below 512 MiB.

- [ ] **Step 2: Run the performance test**

Run: `pytest tests/performance/test_wiki_build_performance.py -q -m slow`

Expected: PASS. If the CI filesystem cannot meet the approved threshold, optimize
hashing/rendering rather than weakening the threshold.

- [ ] **Step 3: Document the workflow**

Add a README section showing:

```bash
echelon wiki build
echelon wiki status
echelon wiki clean
```

State that output is local at `.echelon/runtime/wiki/`, canonical artifacts remain
under `specs/` and `re/`, Obsidian is optional and not installed, auto-refresh starts
only after the first build, external Git/manual changes require an explicit rebuild,
and `.echelon/local.yml` participates in resolved configuration.

- [ ] **Step 4: Run focused wiki verification**

Run: `pytest tests/unit/test_wiki_discovery.py tests/unit/test_wiki_render.py tests/unit/test_wiki_service.py tests/unit/test_cli_wiki.py tests/unit/test_cli_typer_app.py -q`

Expected: PASS.

- [ ] **Step 5: Run the repository test suite**

Run: `pytest`

Expected: PASS with only the repository's documented skips.

- [ ] **Step 6: Run extension wiring validation**

Run: `bash scripts/bash/dry-run.sh`

Expected: PASS.

- [ ] **Step 7: Inspect scope and commit**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors and only planned wiki/documentation changes.

```bash
git add README.md tests/performance/test_wiki_build_performance.py
git commit -m "docs: document human wiki workflow"
```
