# Echelon Pipeline Matrix

Echelon currently has two independent pipeline choices:

1. **Spec authoring format** in Phase A.
2. **Build execution strategy** in Phase B.

These choices are related because Phase B consumes Phase A artifacts, but they
are not the same switch. Treating them as one decision is a source of operator
confusion.

## Phase A: Spec Authoring Pipelines

| Pipeline | Trigger | Primary output | Human readability | Deterministic validation | Current status |
|---|---|---|---|---|---|
| Standard spec-kit style | `lexicon_gate.enabled: false` | `specs/<id>-*/spec.md` as a rich Markdown feature specification | High: stories, acceptance scenarios, FR/NFR sections, entities, success criteria | Soft quality scoring through Understanding/SAGE | Stable default-compatible path |
| Derived Lexicon controlled grammar | `lexicon_gate.enabled: true` | `specs/<id>-*/requirements.lexicon.md` derived from canonical `spec.md` | High for canonical `spec.md`; derived artifact optimized for machine parsing | Hard `lexicon validate` gate on `requirements.lexicon.md` before soft quality scoring | Supported gate path |
| Lexicon-native replacement | Future explicit `lexicon_gate.artifacts.spec.mode: replace_spec` only | `specs/<id>-*/spec.md` as `ARTIFACT: SPEC` blocks | Lower for humans; optimized for machine parsing | Hard `lexicon validate` gate on `spec.md` | Not currently enabled by default |

The Lexicon gate was introduced to make requirements machine-checkable. It must
not replace `spec.md` during normal Phase A runs because doing so changes the
public Phase A contract. Downstream readers and tools that expect the standard
spec-kit structure need frontmatter-like metadata and narrative sections such as
user stories, success criteria, and key entities.

Echelon's supported dual-artifact contract is:

- `spec.md` is the canonical human and harness feature contract.
- Any controlled grammar form is a separate derived artifact,
  `requirements.lexicon.md`, unless the whole run explicitly opts in to a future
  Lexicon-native replacement mode.
- The derived artifact starts with `# SOURCE: spec.md` and `# SOURCE_SHA256: ...`
  metadata. `lexicon validate --source-ref spec.md` rejects stale derived files
  and rejects derived requirement, acceptance-criteria, or error IDs that are not
  projected from `spec.md`.

## Phase B: Build Execution Pipelines

| Pipeline | Trigger | Build engine | Consumes | Current status |
|---|---|---|---|---|
| Default delivery strategy | `echelon delivery run <id>` | Echelon squad build via `echelon.build` | Published Phase A artifacts under `specs/<id>-*/` | Primary supported path |
| Codegen delivery strategy | `echelon delivery run <id> strategy=codegen` | SOAR CQ-ISC pipeline via `echelon.codegen` | Same published Phase A artifacts; mines requirements into MemPalace | Alternative build path with stricter quality gates |
| Direct build command | `echelon build <id>` | Echelon build skill outside harness | Phase A artifacts | Advanced/manual |
| Direct codegen command | `echelon codegen <id>` | SOAR pipeline outside harness | Phase A artifacts | Advanced/manual |

Build strategy should not change the Phase A spec contract. Both build
strategies should be able to locate the same published `spec.md`, `plan.md`,
`research.md`, `data-model.md`, and `tasks.md` files.

## Supported Combinations

| Phase A format | Phase B default strategy | Phase B codegen strategy | Notes |
|---|---|---|---|
| Standard spec-kit `spec.md` | Supported | Supported | Safest current combination. |
| Standard `spec.md` + derived Lexicon artifact | Supported | Supported | Preserves human contract while enabling hard machine validation. |
| Lexicon `spec.md` replacement | Risky | Risky | Requires every downstream consumer to understand Lexicon grammar; keep behind future explicit opt-in. |

## Current Configuration Risk

`extension/echelon-config.yml` currently enables the Lexicon gate:

```yaml
lexicon_gate:
  enabled: true
```

That now means CARTOGRAPHER keeps `spec.md` in the standard rich Markdown
feature-spec format and writes `requirements.lexicon.md` as a derived validation
artifact.

For standard spec-kit output without the derived Lexicon gate, set:

```yaml
lexicon_gate:
  enabled: false
```

## Recommended Contract

The safer long-term contract is:

1. Keep `spec.md` in the standard rich Markdown feature-spec format.
2. Generate Lexicon controlled grammar as a derived artifact:
   `requirements.lexicon.md`.
3. Run `lexicon validate --source-ref spec.md` against that derived artifact.
4. Make `ARTIFACTS.md` list both artifacts and explain which consumers read each
   file.
5. Only make Lexicon-native `spec.md` available behind an explicit, documented
   opt-in such as `lexicon_gate.mode: replace_spec`.
