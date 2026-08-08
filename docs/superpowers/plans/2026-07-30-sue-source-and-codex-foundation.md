# SUE Source and Codex Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the zero-model-call SUE source-bundle, source-knowledge-map, and
isolated Codex runner foundation while preserving all current SUE CLI behavior.

**Architecture:** Two standard-library-only modules live beside the six SUE
scripts. `sue_source.py` owns deterministic input normalization and provenance;
`sue_runner.py` owns provider execution and evidence metadata. Existing
`sue_challenge.py` remains the compatibility entry point and delegates provider
execution to the new runner.

**Tech Stack:** Python 3.11 standard library, pytest 8, Codex CLI 0.146
contract tests using fake executables

## Global Constraints

- Follow `docs/socratic-understanding/SPECIFICATION.md` and
  `docs/socratic-understanding/DECISIONS.md`.
- Keep cold readers isolated from repository state, other runs, aggregate
  evidence, and user Codex configuration.
- Preserve original source text and locators; adapters never paraphrase or
  invent requirements.
- Keep the standalone SUE path standard-library-only.
- Use `gpt-5.6-luna` with `low` reasoning as the visible economical Codex
  profile; scientific runs must specify provider, model, and reasoning
  explicitly.
- Run no live model calls in this plan.
- Use test-first development and commit after every task.

---

### Task 1: Isolate ambient provider tests and define the economical Codex CLI contract

**Files:**
- Modify: `tests/unit/test_sue_challenge.py`
- Modify: `scripts/sue_challenge.py`
- Modify: `docs/superpowers/specs/2026-07-30-sue-portability-and-evidence-design.md`

**Interfaces:**
- Consumes: existing `resolve_model_command(explicit, env)`
- Produces: `DEFAULT_CODEX_MODEL`, `DEFAULT_CODEX_REASONING_EFFORT`, and
  `RunConfig.model` / `RunConfig.reasoning_effort`

- [ ] **Step 1: Make the ambient-provider test deterministic**

Change the existing default test to isolate it from `CODEX_THREAD_ID`,
`CODEX_CI`, and `ECHELON_LLM`:

```python
def test_defaults_are_15_claude_300(self, monkeypatch):
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_CI", raising=False)
    monkeypatch.delenv("ECHELON_LLM", raising=False)
    config = sue.parse_args(["spec.md"])
    assert config.spec_path == Path("spec.md")
    assert config.max_questions == 15
    assert config.model_command == "claude"
    assert config.timeout_seconds == 300
```

- [ ] **Step 2: Add failing tests for explicit Codex model selection**

Add these cases under `TestArgumentHandling`:

```python
def test_codex_uses_visible_economical_model_profile(self):
    config = sue.parse_args([
        "spec.md", "--model-cmd", "codex=codex",
    ])
    assert config.model == "gpt-5.6-luna"
    assert config.reasoning_effort == "low"

def test_codex_model_and_reasoning_can_be_overridden(self):
    config = sue.parse_args([
        "spec.md",
        "--model-cmd", "codex=codex",
        "--model", "gpt-5.6-terra",
        "--reasoning-effort", "medium",
    ])
    assert config.model == "gpt-5.6-terra"
    assert config.reasoning_effort == "medium"

def test_non_codex_model_override_is_rejected(self, capsys):
    assert sue.main([
        "spec.md",
        "--model-cmd", "claude=claude",
        "--model", "gpt-5.6-luna",
    ]) == sue.EXIT_BAD_INPUT
    assert "--model is supported only for codex" in capsys.readouterr().err
```

Update the dataclass-field expectation to include `model` and
`reasoning_effort`.

- [ ] **Step 3: Run the focused tests and verify the new cases fail**

Run:

```bash
pytest -q \
  tests/unit/test_sue_challenge.py::TestArgumentHandling::test_codex_uses_visible_economical_model_profile \
  tests/unit/test_sue_challenge.py::TestArgumentHandling::test_codex_model_and_reasoning_can_be_overridden \
  tests/unit/test_sue_challenge.py::TestArgumentHandling::test_non_codex_model_override_is_rejected
```

Expected: failures because the constants, fields, and arguments do not exist.

- [ ] **Step 4: Add the model-selection fields and arguments**

Add:

```python
DEFAULT_CODEX_MODEL = "gpt-5.6-luna"
DEFAULT_CODEX_REASONING_EFFORT = "low"
CODEX_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")
```

Extend `RunConfig`:

```python
@dataclass(frozen=True)
class RunConfig:
    spec_path: Path
    max_questions: int
    model_command: str
    timeout_seconds: float
    model_protocol: str = "claude-stdin"
    model: str | None = None
    reasoning_effort: str | None = None
```

Add parser options:

```python
parser.add_argument(
    "--model",
    default=None,
    help=(
        "Codex model override; Codex defaults visibly to "
        f"{DEFAULT_CODEX_MODEL!r}"
    ),
)
parser.add_argument(
    "--reasoning-effort",
    choices=CODEX_REASONING_EFFORTS,
    default=None,
    help=(
        "Codex reasoning effort; Codex defaults visibly to "
        f"{DEFAULT_CODEX_REASONING_EFFORT!r}"
    ),
)
```

After provider resolution, assign values only for `codex-stdin`; reject model
arguments for other protocols.

- [ ] **Step 5: Run the full challenge tests**

Run:

```bash
pytest -q tests/unit/test_sue_challenge.py
```

Expected: all challenge tests pass under the ambient Codex environment.

- [ ] **Step 6: Commit**

```bash
git add scripts/sue_challenge.py tests/unit/test_sue_challenge.py \
  docs/superpowers/specs/2026-07-30-sue-portability-and-evidence-design.md
git commit -m "feat(sue): make Codex model selection explicit"
```

---

### Task 2: Define immutable source-bundle and provenance primitives

**Files:**
- Create: `scripts/sue_source.py`
- Create: `tests/unit/test_sue_source.py`

**Interfaces:**
- Produces:
  - `SourceRef(document_id: str, locator_kind: str, locator: str)`
  - `SourceDocument(id: str, source_uri: str, media_type: str, digest: str, text: str)`
  - `DeclaredRelation(predicate: str, target_unit_id: str, source_refs: tuple[SourceRef, ...])`
  - `SourceUnit(id: str, kind: str, text: str, normative_level: str, source_refs: tuple[SourceRef, ...], declared_relations: tuple[DeclaredRelation, ...], situation: ControlledSituation | None)`
  - `GlossaryTerm(canonical: str, aliases: tuple[str, ...], source_refs: tuple[SourceRef, ...])`
  - `SUESourceBundle(...)`
  - `canonical_json(value: object) -> str`
  - `sha256_text(text: str) -> str`
  - `resolve_source_ref(bundle: SUESourceBundle, ref: SourceRef) -> str`

- [ ] **Step 1: Write failing canonicalization and locator tests**

Create an import helper matching the existing script tests, then add:

```python
def test_bundle_digest_is_canonical_and_stable():
    bundle_a = source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(),),
        units=(_unit(),),
    )
    bundle_b = source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(),),
        units=(_unit(),),
    )
    assert bundle_a.snapshot_digest == bundle_b.snapshot_digest
    assert len(bundle_a.snapshot_digest) == 64

def test_line_range_resolves_exact_original_text():
    document = source.SourceDocument.from_text(
        id="requirements",
        source_uri="requirements.md",
        media_type="text/markdown",
        text="# Checkout\nLine two\nLine three\n",
    )
    bundle = source.make_bundle(
        bundle_id="checkout",
        adapter_id="markdown-lexicon",
        documents=(document,),
        units=(),
    )
    ref = source.SourceRef("requirements", "line-range", "L2-L3")
    assert source.resolve_source_ref(bundle, ref) == "Line two\nLine three"

def test_changed_document_changes_snapshot_digest():
    first = _bundle_with_text("The system MUST save.")
    second = _bundle_with_text("The system MUST not save.")
    assert first.snapshot_digest != second.snapshot_digest
```

Add negative tests for an unknown document, malformed `Lx-Ly`, an out-of-range
line, duplicate document IDs, and duplicate unit IDs.

- [ ] **Step 2: Run tests and verify import failure**

Run:

```bash
pytest -q tests/unit/test_sue_source.py
```

Expected: failure because `scripts/sue_source.py` does not exist.

- [ ] **Step 3: Implement immutable dataclasses and canonical serialization**

Use frozen dataclasses and tuple-valued collections. Canonical JSON is:

```python
def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
```

`make_bundle` validates identifiers and locators, serializes the bundle with an
empty `snapshot_digest`, then hashes that canonical representation.

`SourceDocument.from_text` hashes the exact UTF-8 text:

```python
@classmethod
def from_text(cls, *, id: str, source_uri: str, media_type: str, text: str):
    return cls(
        id=id,
        source_uri=source_uri,
        media_type=media_type,
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
    )
```

- [ ] **Step 4: Run the source primitive tests**

Run:

```bash
pytest -q tests/unit/test_sue_source.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/sue_source.py tests/unit/test_sue_source.py
git commit -m "feat(sue): add immutable source bundle primitives"
```

---

### Task 3: Add Markdown/Lexicon and generic-manifest adapters

**Files:**
- Modify: `scripts/sue_source.py`
- Modify: `tests/unit/test_sue_source.py`

**Interfaces:**
- Produces:
  - `SUESourceError(code: str, message: str)`
  - `load_source_bundle(path: Path, source_format: str = "auto") -> SUESourceBundle`
  - `load_markdown_lexicon(path: Path) -> SUESourceBundle`
  - `load_generic_manifest(path: Path) -> SUESourceBundle`

- [ ] **Step 1: Add failing Markdown/Lexicon adapter tests**

Cover current source shapes and provenance:

```python
def test_markdown_adapter_preserves_explicit_requirement_id(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# Requirements\n\n- **FR-001**: The system MUST save.\n")
    bundle = source.load_source_bundle(path)
    assert [unit.id for unit in bundle.units] == ["FR-001"]
    assert bundle.units[0].text == "The system MUST save."
    assert bundle.units[0].source_refs[0].locator == "L3-L3"

def test_lexicon_adapter_extracts_controlled_situation(tmp_path):
    path = tmp_path / "rules.lex"
    path.write_text(
        "REQ: REQ-001\n"
        "GIVEN: an authenticated user\n"
        "WHEN: the user saves\n"
        "THEN: the record persists\n"
    )
    bundle = source.load_source_bundle(path)
    situation = bundle.units[0].situation
    assert situation.given == "an authenticated user"
    assert situation.when == "the user saves"
    assert situation.then == "the record persists"

def test_normative_bullet_gets_locator_id(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# Rules\n\n- The cache MUST expire after 10 minutes.\n")
    bundle = source.load_source_bundle(path)
    assert bundle.units[0].id.endswith(":L3-L3")
    assert bundle.units[0].normative_level == "must"

def test_unstructured_prose_is_inconclusive(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Some thoughts about a future product.\n")
    with pytest.raises(source.SUESourceError) as error:
        source.load_source_bundle(path)
    assert error.value.code == "INCONCLUSIVE_INPUT"
```

- [ ] **Step 2: Add failing manifest tests**

Use a relative document path:

```python
def test_manifest_accepts_non_echelon_unit_ids(tmp_path):
    document = tmp_path / "requirements.txt"
    document.write_text("Payment retries stop after three attempts.\n")
    manifest = tmp_path / "requirements.sue.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "bundle_id": "payments",
        "documents": [{
            "id": "rules",
            "path": "requirements.txt",
            "media_type": "text/plain",
        }],
        "units": [{
            "id": "PAYMENT-RETRY",
            "kind": "rule",
            "text": "Payment retries stop after three attempts.",
            "normative_level": "must",
            "source_refs": [{
                "document_id": "rules",
                "locator_kind": "line-range",
                "locator": "L1-L1",
            }],
        }],
        "glossary": [],
    }))
    bundle = source.load_source_bundle(manifest, "manifest")
    assert bundle.units[0].id == "PAYMENT-RETRY"
```

Add tests that reject path traversal, source-text mismatch, incorrect supplied
digest, missing referenced documents, unresolved relation targets, and
one-to-many glossary aliases.

- [ ] **Step 3: Run adapter tests and verify failure**

Run:

```bash
pytest -q tests/unit/test_sue_source.py -k "adapter or manifest or inconclusive or lexicon or normative"
```

Expected: failures because adapter functions do not exist.

- [ ] **Step 4: Implement both adapters**

The Markdown/Lexicon adapter reuses the existing definition-site patterns but
returns source units rather than a set of IDs. It emits a unit only for an
explicit requirement/acceptance shape or a normative modal.

The manifest adapter:

1. loads JSON;
2. resolves document paths relative to the manifest directory;
3. rejects paths escaping that directory;
4. reads exact UTF-8 content;
5. verifies optional document digests;
6. constructs units, glossary, and declared relations;
7. resolves every source reference; and
8. compares each unit's verbatim text with its referenced source span.

- [ ] **Step 5: Run all source tests**

Run:

```bash
pytest -q tests/unit/test_sue_source.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/sue_source.py tests/unit/test_sue_source.py
git commit -m "feat(sue): add source bundle adapters"
```

---

### Task 4: Build the deterministic SourceKnowledgeMap

**Files:**
- Modify: `scripts/sue_source.py`
- Modify: `tests/unit/test_sue_source.py`

**Interfaces:**
- Produces:
  - `SourceKnowledgeMap(bundle_id: str, units_by_id: dict[str, SourceUnit], outgoing: dict[str, tuple[DeclaredRelation, ...]], glossary_by_alias: dict[str, tuple[str, ...]])`
  - `build_source_knowledge_map(bundle: SUESourceBundle) -> SourceKnowledgeMap`
  - `canonical_glossary_match(knowledge_map: SourceKnowledgeMap, label: str) -> str | None`

- [ ] **Step 1: Add failing knowledge-map tests**

```python
def test_source_map_contains_only_declared_relations():
    bundle = _bundle_with_declared_dependency("PAYMENT-RETRY", "PAYMENT-LIMIT")
    knowledge = source.build_source_knowledge_map(bundle)
    assert tuple(knowledge.units_by_id) == ("PAYMENT-LIMIT", "PAYMENT-RETRY")
    assert knowledge.outgoing["PAYMENT-RETRY"][0].target_unit_id == "PAYMENT-LIMIT"

def test_unambiguous_declared_alias_canonicalizes():
    knowledge = source.build_source_knowledge_map(
        _bundle_with_glossary("customer", ("user", "account holder"))
    )
    assert source.canonical_glossary_match(knowledge, "users") == "customer"

def test_ambiguous_alias_remains_unmatched():
    knowledge = source.build_source_knowledge_map(
        _bundle_with_two_terms_sharing_alias("record")
    )
    assert source.canonical_glossary_match(knowledge, "record") is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest -q tests/unit/test_sue_source.py -k "source_map or canonicalizes or ambiguous_alias"
```

Expected: failures because the map functions do not exist.

- [ ] **Step 3: Implement deterministic adjacency and glossary indexes**

Sort all map keys and relation tuples. `canonical_glossary_match` applies only:

1. lowercase and whitespace normalization;
2. leading article removal;
3. conservative singularization already used by V3; and
4. exact match against explicitly declared canonical terms or aliases.

Return `None` when zero or more than one canonical term matches.

- [ ] **Step 4: Run source tests**

Run:

```bash
pytest -q tests/unit/test_sue_source.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/sue_source.py tests/unit/test_sue_source.py
git commit -m "feat(sue): add deterministic source knowledge map"
```

---

### Task 5: Define the cold-reader runner and hardened Codex invocation

**Files:**
- Create: `scripts/sue_runner.py`
- Create: `tests/unit/test_sue_runner.py`

**Interfaces:**
- Produces:
  - `ColdReaderRequest`
  - `ColdReaderResult`
  - `ModelInvocation`
  - `build_model_invocation(request: ColdReaderRequest, workdir: Path) -> ModelInvocation`
  - `parse_codex_jsonl(raw: str) -> tuple[dict | None, dict | None]`
  - `run_cold_reader(request: ColdReaderRequest) -> ColdReaderResult`

- [ ] **Step 1: Add failing request and invocation tests**

```python
def test_codex_invocation_is_cold_and_explicit(tmp_path):
    request = runner.ColdReaderRequest(
        run_id="run-1",
        provider="codex",
        command="codex",
        model="gpt-5.6-luna",
        reasoning_effort="low",
        prompt="PROMPT",
        timeout_seconds=30,
        output_schema={"type": "object"},
    )
    invocation = runner.build_model_invocation(request, tmp_path)
    assert invocation.argv == [
        "codex", "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox", "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--model", "gpt-5.6-luna",
        "-c", 'model_reasoning_effort="low"',
        "--output-schema", str(tmp_path / "output-schema.json"),
        "--json",
        "--output-last-message", str(tmp_path / "final.json"),
        "-",
    ]
    assert invocation.stdin_text == "PROMPT"

def test_scientific_codex_request_rejects_missing_model():
    with pytest.raises(runner.RunnerConfigurationError):
        runner.ColdReaderRequest(
            run_id="run-1",
            provider="codex",
            command="codex",
            model=None,
            reasoning_effort="low",
            prompt="PROMPT",
            timeout_seconds=30,
            scientific=True,
            output_schema={"type": "object"},
        )
```

Add cases for unsupported providers, invalid reasoning effort, command parse
failure, output schema absence in scientific mode, and prompt presence only on
stdin.

- [ ] **Step 2: Add failing JSONL usage tests**

```python
def test_parse_codex_jsonl_extracts_usage_and_reported_model():
    raw = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
        json.dumps({
            "type": "turn.completed",
            "model": "gpt-5.6-luna",
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 20,
                "output_tokens": 30,
                "reasoning_output_tokens": 5,
            },
        }),
    ])
    metadata, usage = runner.parse_codex_jsonl(raw)
    assert metadata["thread_id"] == "thread-1"
    assert metadata["model_reported"] == "gpt-5.6-luna"
    assert usage["input_tokens"] == 100
```

- [ ] **Step 3: Run runner tests and verify import failure**

Run:

```bash
pytest -q tests/unit/test_sue_runner.py
```

Expected: failure because `scripts/sue_runner.py` does not exist.

- [ ] **Step 4: Implement request/result dataclasses and pure builders**

`ColdReaderRequest` validates in `__post_init__`. `ColdReaderResult` records:

```python
@dataclass(frozen=True)
class ColdReaderResult:
    run_id: str
    status: str
    provider: str
    model_requested: str | None
    model_reported: str | None
    reasoning_effort: str | None
    protocol: str
    argv_redacted: tuple[str, ...]
    duration_seconds: float
    exit_code: int | None
    raw_output: str
    final_output: str
    stderr: str
    raw_output_digest: str
    final_output_digest: str
    usage: dict | None
```

Do not store the prompt or schema contents in `argv_redacted`.

- [ ] **Step 5: Implement the subprocess runner**

Use `tempfile.TemporaryDirectory(prefix="sue-reader-")`,
`start_new_session=True`, the existing process-group timeout cleanup pattern,
and exact statuses:

- `success`
- `timeout`
- `launch_missing`
- `transport_error`
- `unusable_output`

For Codex, return the `--output-last-message` file as `final_output` and JSONL
stdout as `raw_output`. Preserve stderr and nonzero exit codes.

- [ ] **Step 6: Add and run fake-Codex execution tests**

The fake executable validates arguments, consumes stdin, writes its final JSON
to the path following `--output-last-message`, and prints JSONL usage:

```python
def test_fake_codex_runner_captures_final_output_and_usage(tmp_path):
    fake = _make_fake_codex(tmp_path)
    result = runner.run_cold_reader(_codex_request(fake))
    assert result.status == "success"
    assert json.loads(result.final_output) == {"questions": []}
    assert result.usage["input_tokens"] == 12
    assert result.model_requested == "gpt-5.6-luna"
    assert result.argv_redacted[-1] == "-"
```

Add timeout, missing executable, malformed JSONL, missing final file, nonzero
exit, and neutral-working-directory tests.

Run:

```bash
pytest -q tests/unit/test_sue_runner.py
```

Expected: all runner tests pass without any real provider call.

- [ ] **Step 7: Commit**

```bash
git add scripts/sue_runner.py tests/unit/test_sue_runner.py
git commit -m "feat(sue): add isolated cold reader runner"
```

---

### Task 6: Delegate V1 Codex calls to the runner with strict output schemas

**Files:**
- Modify: `scripts/sue_challenge.py`
- Modify: `tests/unit/test_sue_challenge.py`
- Modify: `tests/unit/test_sue_runner.py`

**Interfaces:**
- Consumes: `sue_runner.ColdReaderRequest`, `sue_runner.run_cold_reader`
- Produces:
  - `ROUND1_OUTPUT_SCHEMA`
  - `ROUND2_OUTPUT_SCHEMA`
  - `run_model_call(config, prompt, output_schema=None) -> CallOutcome`

- [ ] **Step 1: Add failing schema and delegation tests**

```python
def test_codex_round_invocation_uses_schema_and_final_output(tmp_path, monkeypatch):
    captured = {}

    def fake_run(request):
        captured["request"] = request
        final_output = '{"questions":[]}'
        return sue.runner.ColdReaderResult(
            run_id=request.run_id,
            status="success",
            provider=request.provider,
            model_requested=request.model,
            model_reported=request.model,
            reasoning_effort=request.reasoning_effort,
            protocol="codex-stdin",
            argv_redacted=("codex", "exec", "-"),
            duration_seconds=0.1,
            exit_code=0,
            raw_output="",
            final_output=final_output,
            stderr="",
            raw_output_digest=sue.runner.sha256_text(""),
            final_output_digest=sue.runner.sha256_text(final_output),
            usage=None,
        )

    monkeypatch.setattr(sue.runner, "run_cold_reader", fake_run)
    config = sue.RunConfig(
        spec_path=tmp_path / "spec.md",
        max_questions=1,
        model_command="codex",
        timeout_seconds=10,
        model_protocol="codex-stdin",
        model="gpt-5.6-luna",
        reasoning_effort="low",
    )
    outcome = sue.run_model_call(
        config, "PROMPT", output_schema=sue.ROUND1_OUTPUT_SCHEMA
    )
    assert outcome.stdout == '{"questions":[]}'
    assert captured["request"].model == "gpt-5.6-luna"
    assert captured["request"].reasoning_effort == "low"
    assert captured["request"].output_schema == sue.ROUND1_OUTPUT_SCHEMA
```

Add tests that Claude and Copilot continue to use their current protocols and
that round 1 and round 2 receive different schemas.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
pytest -q tests/unit/test_sue_challenge.py -k "schema or delegation"
```

Expected: failures because schemas and delegation are absent.

- [ ] **Step 3: Load `sue_runner.py` using the standalone pattern**

Add a local `_load_runner()` beside the other module-level helpers. Alias
`ModelInvocation` only where existing callers need it; keep the V1
`CallOutcome` compatibility dataclass and translate runner statuses:

```python
kind_map = {
    "success": "ok",
    "timeout": "timeout",
    "launch_missing": "launch_missing",
    "transport_error": "failed",
    "unusable_output": "failed",
}
```

- [ ] **Step 4: Define round-specific JSON schemas**

`ROUND1_OUTPUT_SCHEMA` requires exactly a `questions` array with the current
question fields and `additionalProperties: false`.

`ROUND2_OUTPUT_SCHEMA` requires exactly an `answers` array with the current
answer fields, verdict enum, and `additionalProperties: false`.

The existing strict Python validators remain authoritative for semantic checks
such as ID bijection and line bounds.

- [ ] **Step 5: Pass schemas from both rounds**

Extend `execute_round` with a final `output_schema: dict | None = None`
parameter and pass:

```python
round1 = execute_round(
    config,
    build_round1_prompt(spec, config.max_questions),
    lambda obj: validate_round1(obj, config.max_questions),
    1,
    spec_dir,
    ROUND1_OUTPUT_SCHEMA,
)
round2 = execute_round(
    config,
    build_round2_prompt(spec, [(q.id, q.question) for q in questions]),
    lambda obj: validate_round2(obj, questions),
    2,
    spec_dir,
    ROUND2_OUTPUT_SCHEMA,
)
```

Update existing unit calls with the appropriate schema only when they test
Codex runner behavior; other stubs may keep `None`.

- [ ] **Step 6: Run challenge and runner tests**

Run:

```bash
pytest -q tests/unit/test_sue_challenge.py tests/unit/test_sue_runner.py
```

Expected: all tests pass with zero live model calls.

- [ ] **Step 7: Commit**

```bash
git add scripts/sue_challenge.py tests/unit/test_sue_challenge.py \
  tests/unit/test_sue_runner.py
git commit -m "feat(sue): harden Codex challenge transport"
```

---

### Task 7: Document and verify the zero-call foundation

**Files:**
- Modify: `README.md`
- Modify: `docs/socratic-understanding/HANDOFF.md`
- Modify: `docs/socratic-understanding/DECISIONS.md`
- Modify: `docs/socratic-understanding/OPEN-QUESTIONS.md`
- Modify: `docs/superpowers/specs/2026-07-30-sue-portability-and-evidence-design.md`

**Interfaces:**
- Documents the exact runnable low-cost command:

```bash
python3 scripts/sue_challenge.py requirements.md \
  --model-cmd 'codex=codex' \
  --model gpt-5.6-luna \
  --reasoning-effort low
```

- [ ] **Step 1: Update authoritative decision records**

Add accepted decisions:

- source portability uses deterministic provenance-preserving bundles;
- Codex scientific runs pin provider, model, and reasoning;
- `gpt-5.6-luna`/`low` is the first economical experiment profile, not a claim
  that the model satisfies A1.

Resolve OQ-015 as fixed and record the new source/runner symbols in the handoff
capability map. Do not claim A1 or live Codex success.

- [ ] **Step 2: Update README usage**

Add the explicit economical command and explain:

- source content is sent to the selected provider;
- the model is shown in preflight/evidence;
- lower cost can reduce extraction quality;
- A1 decides whether that exact profile is usable.

- [ ] **Step 3: Run all focused SUE tests in both environments**

Run:

```bash
pytest -q \
  tests/unit/test_sue_challenge.py \
  tests/unit/test_sue_consensus.py \
  tests/unit/test_sue_reproducibility.py \
  tests/unit/test_sue_dialectic.py \
  tests/unit/test_sue_jgraph.py \
  tests/unit/test_sue_auto.py \
  tests/unit/test_sue_source.py \
  tests/unit/test_sue_runner.py
```

Then run with provider markers cleared:

```bash
env -u CODEX_THREAD_ID -u CODEX_CI -u ECHELON_LLM \
  pytest -q \
  tests/unit/test_sue_challenge.py \
  tests/unit/test_sue_consensus.py \
  tests/unit/test_sue_reproducibility.py \
  tests/unit/test_sue_dialectic.py \
  tests/unit/test_sue_jgraph.py \
  tests/unit/test_sue_auto.py \
  tests/unit/test_sue_source.py \
  tests/unit/test_sue_runner.py
```

Expected: every focused test passes in both environments.

- [ ] **Step 4: Verify no provider was called**

Inspect test output and source changes:

```bash
git diff --check
git status --short
```

Confirm no new files exist under `sue-evidence/` and no SUE report timestamp
changed.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/socratic-understanding \
  docs/superpowers/specs/2026-07-30-sue-portability-and-evidence-design.md
git commit -m "docs: publish portable SUE foundation"
```

## Completion gate

This plan is complete only when:

- the source-bundle, adapters, knowledge map, and cold runner exist;
- the economical Codex model is explicit and test-covered;
- all focused tests pass with and without ambient Codex markers;
- the current six SUE tools retain their existing offline behavior; and
- no live model calls were made.

After this gate, create and execute
`2026-07-30-sue-v3-bundle-evidence.md`. Do not run the Codex smoke or A1 from
this plan.
