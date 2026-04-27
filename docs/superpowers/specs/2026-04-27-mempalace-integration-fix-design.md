# MemPalace Integration Fix — Design

**Date:** 2026-04-27
**Status:** Approved

---

## Problem Summary

The echelon/codegen MemPalace integration has four bugs and no stable per-project wing identity:

1. **drawer_id hash mismatch (Critical)** — `_mcp_write` constructs IDs with MD5[:16]; `add_drawer` uses SHA256[:24]. They never match, so all codegen metadata (`run_id`, `phase`, `run_outcome`) is silently dropped and `backfill_run_outcome` / `backfill_status` are completely broken.
2. **Wing collision (Critical)** — `pipeline_engine.py` derives wing from `self.state_file.parent.name or "codegen"`. With the default relative `Path("codegen-state.json")`, `parent.name` is `""` → every project writes to wing `"codegen"`.
3. **Non-deterministic chunk_index (Medium)** — `hash(self.run_id) & 0xFFFF` uses Python's randomised `hash()`, producing different values per process restart and causing duplicate drawers instead of upserts.
4. **Dead memory-config.yml (Low)** — `install.sh` writes `~/.echelon/memory-config.yml` but `MempalaceConfig()` reads `~/.mempalace/config.json`. The echelon config is never loaded; palace path is correct only by coincidence.

Additionally there is no stable, portable wing identity. The current folder-name approach is non-unique (many projects have `src`) and not portable across clones of the same repo.

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Wing config location | `echelon.yml` `mempalace.wing` | Already committed per-project; clones inherit wing automatically |
| Wing provisioning | Auto-suggest + interactive confirm in `echelon init` | Gives user something to react to; falls back gracefully without git remote |
| Missing wing behaviour | Hard fail in codegen | Forces one-time migration; keeps bug-free invariant |
| `echelon init` idempotency | Wing already set → skip, print `✓ already configured` | Safe to re-run on existing projects |
| Collision detection | Both `echelon init` (gate) and `mine` time (warning) | Init prevents the problem; mine-time catches independent-init collisions |
| `--wing` CLI override | Kept on `codegen run` | Power-user escape hatch; takes precedence over `echelon.yml` |
| Wing precedence | `--wing` CLI → `echelon.yml` → hard fail | Explicit beats configured; unconfigured is an error |

---

## Architecture

### 1. `MemPalaceContext` — single source of truth

**New file:** `src/codegen/memory/context.py`

```python
@dataclass
class MemPalaceContext:
    wing: str         # stable project identity
    run_id: str       # unique per pipeline run
    palace_path: str  # resolved from MempalaceConfig()
```

**Factory:**
```python
@classmethod
def from_project(
    cls,
    project_dir: Path,
    run_id: str,
    wing_override: str | None = None,
) -> "MemPalaceContext":
```

Resolution order:
1. `wing_override` (from `--wing` CLI arg)
2. `echelon.yml` → `mempalace.wing`
3. Hard fail: `"wing not set in echelon.yml — run 'echelon init' to configure it"`

`palace_path` always comes from `MempalaceConfig().palace_path` (env var `MEMPALACE_PALACE_PATH` → `~/.mempalace/config.json` → default `~/.mempalace/palace`).

`MemPalaceReader`, `MemPalaceWriter`, and `RequirementsMiner` all take `MemPalaceContext` in their constructors instead of receiving `wing`, `run_id`, `palace_path` as separate arguments.

---

### 2. Wing provisioning in `echelon init`

**Modified:** `src/echelon/cli.py` → `_cmd_init()`

New step inserted after deploy config validation, before `deploy-init.sh`.

**Auto-suggest logic** (in order):
1. `git remote get-url origin` → extract final path component without `.git` suffix → e.g. `my-app`
2. Fallback: `{dirname}-{sha256(abs(project_dir))[:6]}` → e.g. `my-app-a3f2b8` (stable, unique)

**Flow:**
```
wing in echelon.yml already?
  YES → print "✓ wing: <name> already configured" → skip (idempotent)
  NO  → compute suggestion
        prompt: "Wing name for MemPalace memory [<suggestion>]: "
        user Enter = accept suggestion, or type override
        → collision check (see §3)
          CLEAN  → write mempalace.wing into echelon.yml
                   print "✓ wing: <name> written to echelon.yml"
          COLLISION → re-prompt (loop); user may retype same name to force-accept
```

**`echelon.yml` update strategy:** PyYAML round-trip — only add/update the `mempalace:` block, all other keys preserved.

---

### 3. Collision detection

**New file:** `src/codegen/memory/collision.py`

```python
def check_wing_collision(
    wing: str,
    project_dir: Path,
    palace_path: str,
) -> list[str]:
    """Returns list of foreign source_file paths found under this wing, or []."""
```

**Logic:**
- Fetch up to 20 drawers where `wing == <name>` using metadata-only query (no embedding computation)
- Filter drawers whose `source_file` metadata does not start with `str(project_dir)`
- Return the foreign paths

**Call sites:**

| Site | Behaviour on collision |
|---|---|
| `echelon init` | Re-prompt user; same name entered twice = force-accept |
| `RequirementsMiner.mine_file()` first call | Print warning, continue (non-fatal) |

Warning message:
```
⚠  Wing 'my-app' already has drawers from a different project:
     /Users/other/other-project/spec.md
   Choose a different wing name, or re-enter the same name to share memory intentionally.
```

---

### 4. Bug fixes in `MemPalaceWriter`

**Modified:** `src/codegen/memory/mempalace_writer.py`

**Fix 1 — drawer_id hash (Critical)**

Replace local MD5-based ID construction with SHA256[:24] matching `add_drawer`:
```python
drawer_id = f"drawer_{wing}_{room}_{hashlib.sha256((source_file + str(chunk_index)).encode()).hexdigest()[:24]}"
```
`collection.update()`, `backfill_run_outcome()`, and `backfill_status()` now target the correct document.

**Fix 2 — chunk_index determinism (Medium)**

Replace `hash(self.run_id) & 0xFFFF` with:
```python
chunk_index = int(hashlib.sha256(self.run_id.encode()).hexdigest(), 16) & 0xFFFF
```
Same `run_id` always produces the same slot across process restarts.

**Fix 3 — dead memory-config.yml (Low)**

Remove the `memory-config.yml` write step from `scripts/install.sh`. `MemPalaceContext.from_project()` calls `MempalaceConfig()` directly, which already resolves correctly via env var or its own default (`~/.mempalace/palace`).

**Fix 4 — misleading method names**

Rename `_mcp_write` → `_write_drawer` and `_mcp_update_metadata` → `_update_drawer_metadata`. Update ADR-004 comment to reflect direct Python import usage.

---

### 5. Threading through the pipeline

**Wing precedence:** `--wing` CLI arg → `echelon.yml mempalace.wing` → hard fail

**`codegen run` CLI** (`codegen_cli.py`):
- After `engine.initialize()` returns `pipeline_id`, construct `ctx = MemPalaceContext.from_project(Path.cwd(), run_id=pipeline_id, wing_override=args.wing)`
- Pass `ctx` to `engine.run_re_phase(ctx)` and store on engine via `engine.set_context(ctx)`

**`PipelineEngine`** (`pipeline_engine.py`):
- Accept context via `set_context(ctx: MemPalaceContext)`
- Replace `wing = self.state_file.parent.name or "codegen"` with `ctx.wing`
- `_get_mempalace_writer()` constructs `MemPalaceWriter(ctx)` instead of `MemPalaceWriter(wing=..., run_id=...)`

**`RequirementsMiner`**:
- Constructor: `__init__(self, ctx: MemPalaceContext)`
- `mine_file()` calls `check_wing_collision()` lazily on first write (once per miner instance)

**`codegen requirements mine` CLI**:
- Constructs `ctx = MemPalaceContext.from_project(Path.cwd(), run_id="manual", wing_override=args.wing)`
- `--wing` arg kept for override; without it, reads from `echelon.yml`

**`MemPalaceReader`**:
- Constructor: `__init__(self, ctx: MemPalaceContext)`
- Uses `ctx.palace_path` for `_get_collection()` instead of calling `MempalaceConfig()` each time

---

## Files Changed

| File | Change |
|---|---|
| `src/codegen/memory/context.py` | **New** — `MemPalaceContext` dataclass + `from_project()` factory |
| `src/codegen/memory/collision.py` | **New** — `check_wing_collision()` |
| `src/codegen/memory/mempalace_writer.py` | Fix hashes, rename methods, take `ctx` |
| `src/codegen/memory/mempalace_reader.py` | Take `ctx` instead of bare `wing` |
| `src/codegen/memory/requirements_miner.py` | Take `ctx`, add collision check on first mine |
| `src/codegen/pipeline/pipeline_engine.py` | `set_context()`, replace wing derivation |
| `src/codegen/cli/codegen_cli.py` | Construct `ctx`, keep `--wing` as override |
| `src/echelon/cli.py` | Add wing provisioning step to `_cmd_init()` |
| `extension/commands/echelon.init.md` | Document new wing provisioning step |
| `extension/echelon-config.yml` | Add `mempalace:` block template |
| `scripts/install.sh` | Remove dead `memory-config.yml` write |
| `extension/commands/echelon.codegenlight.md` | Replace `WING=$(basename $(pwd))` with `MemPalaceContext`-compatible wing read from `echelon.yml` |
| `extension/commands/echelon.codegen.md` | Same — replace `WING` derivation |

---

## Non-goals

- Migration of existing MemPalace data — drawers written under `"codegen"` wing are left in place; new runs write under the project wing
- Deduplication of legacy data
- UI for browsing wings or drawers
