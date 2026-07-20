# Canonical Command Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every internal Echelon command prompt load from a configurable Echelon content root and prove prompt correctness without invoking an LLM.

**Architecture:** Add one shared content-root resolver and one deterministic command renderer under `harness`. CLI, coordinator, review-loop, and fulfillment call sites will consume those APIs instead of provider projections. Provider adapters remain responsible only for executing the already-rendered prompt.

**Tech Stack:** Python 3.12, `pathlib`, PyYAML through the existing config cascade, pytest, Typer CLI tests, existing fake AI provider boundaries.

## Global Constraints

- Resolution precedence is explicit caller path, `ECHELON_EXTENSION_ROOT`, `runtime.extension_root`, native `<project>/.echelon`, then legacy `<project>/.specify/extensions/echelon`.
- Relative configured roots resolve from the project root.
- Explicit, environment, and configured invalid roots fail; they do not silently fall through.
- Provider projections are never internal content-root candidates.
- Interactive slash-command projections remain unchanged.
- No unit test may start a real Claude, Codex, Copilot, Opencode, or OpenAI-compatible process.
- Preserve unrelated uncommitted files already present in the worktree.

---

### Task 1: Configurable Echelon content-root resolver

**Files:**
- Create: `src/harness/extension_content.py`
- Create: `tests/unit/test_extension_content.py`

**Interfaces:**
- Consumes: `harness.config.get_full_resolved_config(project_root)`.
- Produces: `ExtensionContentError` and `resolve_extension_root(project_root: Path, *, explicit_root: Path | str | None = None) -> Path`.

- [ ] **Step 1: Write failing precedence and validation tests**

Create real temporary content roots with `extension.yml`, `commands/`, and
`workflow/phases/`. Cover explicit-path precedence, environment precedence,
`runtime.extension_root`, native `.echelon`, legacy `.specify`, relative config
paths, and hard failure for an explicitly selected invalid root:

```python
def _content_root(path: Path) -> Path:
    (path / "commands").mkdir(parents=True)
    (path / "workflow" / "phases").mkdir(parents=True)
    (path / "extension.yml").write_text("extension:\n  id: echelon\n")
    return path


def test_resolve_extension_root_prefers_explicit_root(monkeypatch, tmp_path):
    explicit = _content_root(tmp_path / "explicit")
    env_root = _content_root(tmp_path / "environment")
    monkeypatch.setenv("ECHELON_EXTENSION_ROOT", str(env_root))
    assert resolve_extension_root(tmp_path, explicit_root=explicit) == explicit.resolve()


def test_resolve_extension_root_uses_configured_relative_root(tmp_path):
    configured = _content_root(tmp_path / "runtime-content")
    (tmp_path / ".echelon").mkdir(exist_ok=True)
    (tmp_path / ".echelon" / "config.yml").write_text(
        "runtime:\n  extension_root: runtime-content\n"
    )
    assert resolve_extension_root(tmp_path) == configured.resolve()


def test_invalid_configured_root_does_not_fall_back(tmp_path):
    _content_root(tmp_path / ".specify/extensions/echelon")
    (tmp_path / ".echelon").mkdir(exist_ok=True)
    (tmp_path / ".echelon" / "config.yml").write_text(
        "runtime:\n  extension_root: missing-content\n"
    )
    with pytest.raises(ExtensionContentError, match="runtime.extension_root"):
        resolve_extension_root(tmp_path)
```

- [ ] **Step 2: Run the resolver tests and verify RED**

Run: `pytest tests/unit/test_extension_content.py -q`

Expected: collection fails because `harness.extension_content` does not exist.

- [ ] **Step 3: Implement the minimal resolver**

Create `src/harness/extension_content.py` with:

```python
from __future__ import annotations

import os
from pathlib import Path

from harness.config import get_full_resolved_config


class ExtensionContentError(RuntimeError):
    pass


_REQUIRED_CONTENT = (
    Path("extension.yml"),
    Path("commands"),
    Path("workflow/phases"),
)


def _candidate(project_root: Path, value: Path | str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else project_root / path).resolve()


def _is_content_root(path: Path) -> bool:
    return (path / "extension.yml").is_file() and all(
        (path / rel).is_dir() for rel in _REQUIRED_CONTENT[1:]
    )


def _require_content_root(path: Path, source: str) -> Path:
    if not _is_content_root(path):
        raise ExtensionContentError(
            f"Invalid Echelon content root from {source}: {path}"
        )
    return path


def resolve_extension_root(
    project_root: Path,
    *,
    explicit_root: Path | str | None = None,
) -> Path:
    root = project_root.resolve()
    if explicit_root is not None:
        return _require_content_root(_candidate(root, explicit_root), "explicit path")
    env_root = os.environ.get("ECHELON_EXTENSION_ROOT", "").strip()
    if env_root:
        return _require_content_root(_candidate(root, env_root), "ECHELON_EXTENSION_ROOT")
    runtime = get_full_resolved_config(root).get("runtime", {})
    configured = runtime.get("extension_root") if isinstance(runtime, dict) else None
    if isinstance(configured, str) and configured.strip():
        return _require_content_root(
            _candidate(root, configured), ".echelon config runtime.extension_root"
        )
    attempted = [root / ".echelon", root / ".specify/extensions/echelon"]
    for path in attempted:
        resolved = path.resolve()
        if _is_content_root(resolved):
            return resolved
    raise ExtensionContentError(
        "Echelon content root not found; attempted: "
        + ", ".join(str(path) for path in attempted)
    )
```

- [ ] **Step 4: Run the resolver tests and verify GREEN**

Run: `pytest tests/unit/test_extension_content.py -q`

Expected: all resolver tests pass without subprocess calls.

- [ ] **Step 5: Commit the resolver**

```bash
git add src/harness/extension_content.py tests/unit/test_extension_content.py
git commit -m "feat: resolve configurable echelon content root"
```

---

### Task 2: Deterministic canonical command renderer

**Files:**
- Modify: `src/harness/extension_content.py`
- Modify: `tests/unit/test_extension_content.py`

**Interfaces:**
- Consumes: a validated root from `resolve_extension_root` and a fixed skill base such as `echelon.review`.
- Produces: `render_command_prompt(extension_root: Path, skill_base: str, arguments: str) -> str`.

- [ ] **Step 1: Write failing renderer tests**

Add tests using real Markdown files. Assert frontmatter removal, replacement of
every `$ARGUMENTS`, absolute path context, phase-contract order, duplicate
elimination, containment, and missing-phase failure:

```python
def test_render_command_prompt_embeds_canonical_phases_once(tmp_path):
    root = _content_root(tmp_path / "content")
    (root / "commands/echelon.review.md").write_text(
        "---\nname: projected-name\n---\n"
        "Review $ARGUMENTS via `workflow/phases/review-1.md`, then "
        "`workflow/phases/review-1.md` and `workflow/phases/review-2.md`.\n"
    )
    (root / "workflow/phases/review-1.md").write_text("FIRST $ARGUMENTS")
    (root / "workflow/phases/review-2.md").write_text("SECOND")

    prompt = render_command_prompt(root, "echelon.review", "005 pr_url=x")

    assert "name: projected-name" not in prompt
    assert "$ARGUMENTS" not in prompt
    assert "005 pr_url=x" in prompt
    assert f"EXTENSION_DIR={root.resolve()}" in prompt
    assert prompt.count("FIRST 005 pr_url=x") == 1
    assert prompt.index("FIRST 005 pr_url=x") < prompt.index("SECOND")


def test_render_command_prompt_rejects_missing_referenced_phase(tmp_path):
    root = _content_root(tmp_path / "content")
    (root / "commands/echelon.review.md").write_text(
        "Read `workflow/phases/missing.md`."
    )
    with pytest.raises(ExtensionContentError, match="missing.md"):
        render_command_prompt(root, "echelon.review", "005")
```

- [ ] **Step 2: Run renderer tests and verify RED**

Run: `pytest tests/unit/test_extension_content.py -q`

Expected: renderer tests fail because `render_command_prompt` is absent.

- [ ] **Step 3: Implement frontmatter stripping, safe reference discovery, and rendering**

Add `COMMANDER_PREAMBLE`, a `workflow/phases/*.md` reference regex,
`_strip_frontmatter`, `_phase_paths`, `_extension_path_context`, and:

```python
def render_command_prompt(
    extension_root: Path,
    skill_base: str,
    arguments: str,
) -> str:
    root = _require_content_root(extension_root.resolve(), "resolved content root")
    command_path = (root / "commands" / f"{skill_base}.md").resolve()
    if command_path.parent != (root / "commands").resolve() or not command_path.is_file():
        raise ExtensionContentError(f"Canonical Echelon command not found: {command_path}")
    command = _strip_frontmatter(command_path.read_text(encoding="utf-8"))
    phases = []
    for relative in _phase_references(command):
        phase_path = (root / relative).resolve()
        if not phase_path.is_relative_to(root) or not phase_path.is_file():
            raise ExtensionContentError(f"Referenced Echelon phase not found: {phase_path}")
        phases.append(
            f"## Embedded phase contract: {relative}\n\n"
            + _strip_frontmatter(phase_path.read_text(encoding="utf-8"))
        )
    body = "\n\n".join([_extension_path_context(root), command, *phases])
    if "$ARGUMENTS" in body:
        body = body.replace("$ARGUMENTS", arguments)
    else:
        body += f"\n\n## Arguments\n{arguments}"
    return COMMANDER_PREAMBLE + body
```

The helper that extracts phase references must preserve first occurrence order
and use a `set[str]` only for de-duplication. Reject `..` and any resolved path
outside `root`.

- [ ] **Step 4: Run renderer tests and verify GREEN**

Run: `pytest tests/unit/test_extension_content.py -q`

Expected: all resolver and renderer tests pass.

- [ ] **Step 5: Commit the renderer**

```bash
git add src/harness/extension_content.py tests/unit/test_extension_content.py
git commit -m "feat: render canonical echelon command prompts"
```

---

### Task 3: Cut direct CLI commands over to canonical content

**Files:**
- Modify: `src/echelon/cli.py:145-150,7460-7485,7595-7670,8249-8260`
- Modify: `tests/unit/test_cli_llm_tool_policy.py`
- Modify: `tests/unit/test_cli_fulfillment_commands.py`

**Interfaces:**
- Consumes: `resolve_extension_root` and `render_command_prompt` from Task 2.
- Produces: all seven `_dispatch_skill_command` routes loading canonical commands while preserving capability gates and provider execution.

- [ ] **Step 1: Rewrite CLI tests to require canonical content and add Opencode coverage**

Replace `.claude` and `.github` fixtures with a helper that creates the
canonical command and its extension markers. Add a test that creates a bogus
provider projection containing `PROJECTED`, a canonical command containing
`CANONICAL $ARGUMENTS`, and asserts the fake provider receives `CANONICAL` but
not `PROJECTED`. Add an Opencode case asserting `AICodingCliProvider.exec_prompt`
is called and `subprocess.run` is not.

- [ ] **Step 2: Run focused CLI tests and verify RED**

Run:

```bash
pytest tests/unit/test_cli_llm_tool_policy.py tests/unit/test_cli_fulfillment_commands.py -q
```

Expected: failures show `_dispatch_skill_command` still searches provider
projection paths and Opencode still uses its native command invocation.

- [ ] **Step 3: Replace provider projection lookup in `_dispatch_skill_command`**

Import the Task 2 APIs. Resolve and render before provider invocation:

```python
try:
    extension_root = resolve_extension_root(project_dir)
    prompt = render_command_prompt(extension_root, skill_base, arguments)
except ExtensionContentError as exc:
    print(f"echelon {command}: {exc}", file=sys.stderr)
    sys.exit(1)
```

Keep Claude's streaming presentation. Route `copilot`, `codex`,
`openai-compatible`, and `opencode` through
`AICodingCliProvider(config).exec_prompt(str(project_dir), prompt)`. Delete the
internal `_find_skill`, `_build_prompt`, `_skill_not_found_msg`, and native
Opencode command branch when no remaining call site uses them.

Change `_installed_extension_or_exit` to call `resolve_extension_root`, retaining
its existing user-facing exit behavior. This makes Phase A and RE controllers
honor the same configurable root.

- [ ] **Step 4: Run focused CLI tests and verify GREEN**

Run:

```bash
pytest tests/unit/test_cli_llm_tool_policy.py tests/unit/test_cli_fulfillment_commands.py -q
```

Expected: all tests pass and no test starts an external CLI.

- [ ] **Step 5: Commit the CLI cutover**

```bash
git add src/echelon/cli.py tests/unit/test_cli_llm_tool_policy.py tests/unit/test_cli_fulfillment_commands.py
git commit -m "refactor: load cli commands from echelon content"
```

---

### Task 4: Cut harness and fulfillment prompt loading over

**Files:**
- Modify: `src/harness/skill_loader.py`
- Modify: `src/harness/coordinator.py:375-386`
- Modify: `src/harness/review_loop.py:704-720`
- Modify: `src/harness/fulfillment_runner.py:20-25,220-250,440-470,567-607`
- Modify: `tests/unit/test_fulfillment_runner.py`
- Create: `tests/unit/test_canonical_skill_loader.py`

**Interfaces:**
- Consumes: Task 2 resolver and renderer.
- Produces: `resolve_llm_prompt(..., extension_root: Path | None = None) -> str` backed only by canonical content.

- [ ] **Step 1: Write failing harness prompt tests**

Create a temporary canonical extension without provider projections and assert:

```python
prompt = resolve_llm_prompt(
    build_command="echelon build",
    arguments="spec 001-demo",
    project_dir=project,
    extension_root=content,
)
assert "CANONICAL BUILD spec 001-demo" in prompt
```

Update fulfillment fixtures to put `echelon.verify-spec.md` and its phase files
under the resolved content root. Assert `FulfillmentRunner` produces an embedded
canonical prompt when `.claude`, `.github`, and `.opencode` do not exist. Keep
the external provider fake so no LLM process starts.

- [ ] **Step 2: Run focused harness tests and verify RED**

Run:

```bash
pytest tests/unit/test_canonical_skill_loader.py tests/unit/test_fulfillment_runner.py -q
```

Expected: canonical-only fixtures fail because current code calls `find_skill`.

- [ ] **Step 3: Make `skill_loader` a compatibility facade over canonical rendering**

Remove provider-path discovery from internal resolution. Implement:

```python
def resolve_llm_prompt(
    build_command: str,
    arguments: str,
    project_dir: Path,
    cli: str | None = None,
    *,
    extension_root: Path | None = None,
) -> str:
    del cli
    skill_base = build_command_to_skill_base(build_command)
    if skill_base is None:
        return COMMANDER_PREAMBLE + arguments
    root = resolve_extension_root(project_dir, explicit_root=extension_root)
    return render_command_prompt(root, skill_base, arguments)
```

Keep `cli` temporarily in the signature to avoid an unrelated caller break;
document that prompt selection is provider-independent.

- [ ] **Step 4: Pass known roots from controllers and update fulfillment**

Have `StrategyCoordinator` pass its resolved runtime-extension root. Have the
review loop resolve canonical content from its base directory. In fulfillment,
replace `find_skill` with `resolve_extension_root` and
`render_command_prompt`; make `_verify_spec_phase_context` accept an extension
root rather than hard-coding `.specify/extensions/echelon`. Preserve the public
`missing_skill` result status for compatibility, but change its reason to
`canonical verify-spec command missing`.

- [ ] **Step 5: Run focused harness tests and verify GREEN**

Run:

```bash
pytest tests/unit/test_canonical_skill_loader.py tests/unit/test_fulfillment_runner.py -q
```

Expected: all tests pass without provider projection directories.

- [ ] **Step 6: Commit the harness cutover**

```bash
git add src/harness/skill_loader.py src/harness/coordinator.py src/harness/review_loop.py src/harness/fulfillment_runner.py tests/unit/test_canonical_skill_loader.py tests/unit/test_fulfillment_runner.py
git commit -m "refactor: use canonical prompts in harness execution"
```

---

### Task 5: Contract checks and full deterministic verification

**Files:**
- Modify: `tests/kernel/test_prompt_references.py`
- Modify: `src/echelon/cli.py:1-15` provider-path documentation

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: repository-level evidence that internal command discovery is projection-independent.

- [ ] **Step 1: Add a static internal-dependency test**

Add a test that inspects internal prompt-loading modules and rejects calls to
`find_skill` or references to `.claude/skills`, `.github/agents`, and
`.opencode/command`, while excluding `provider_scaffolding.py` because it
intentionally owns interactive UX adapters.

```python
def test_internal_command_loading_is_projection_independent():
    internal_loaders = (
        REPO_ROOT / "src/echelon/cli.py",
        REPO_ROOT / "src/harness/skill_loader.py",
    )
    banned = (
        "find_skill(",
        ".claude/skills",
        ".github/agents",
        ".opencode/command",
    )
    violations = []
    for path in internal_loaders:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                violations.append(f"{path.relative_to(REPO_ROOT)}: {token}")
    assert violations == []
```

- [ ] **Step 2: Run the static test and verify RED if any dependency remains**

Run: `pytest tests/kernel/test_prompt_references.py -q`

Expected: FAIL with exact files and patterns because the old loader and CLI
documentation still contain provider projection paths.

- [ ] **Step 3: Remove remaining internal references and update CLI documentation**

Delete stale provider-discovery comments/imports from internal execution paths.
Keep projection paths only in provider scaffolding, extension deployment, and
interactive UX documentation.

- [ ] **Step 4: Run focused and broad verification**

Run:

```bash
pytest tests/unit/test_extension_content.py \
       tests/unit/test_canonical_skill_loader.py \
       tests/unit/test_cli_llm_tool_policy.py \
       tests/unit/test_cli_fulfillment_commands.py \
       tests/unit/test_fulfillment_runner.py \
       tests/kernel/test_prompt_references.py -q
pytest -m unit -q
bash scripts/bash/dry-run.sh
git diff --check
```

Expected: every command exits zero; pytest reports zero failures; dry-run
reports valid extension wiring; `git diff --check` prints nothing.

- [ ] **Step 5: Commit final contracts and documentation**

```bash
git add src/echelon/cli.py tests/kernel/test_prompt_references.py
git commit -m "test: enforce projection-independent command loading"
```
