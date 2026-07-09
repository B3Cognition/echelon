# Prosaic

Prosaic distributes one canonical set of Markdown-with-frontmatter rules,
commands, skills, and subagents into the on-disk formats expected by many AI
coding tools.

Use it when you want to keep `.prosaic/` as the source of truth and generate
tool-specific files such as Claude Code commands or Cursor rules without
hand-maintaining every copy.

## Prerequisites

- Node.js 20 or newer.
- npm.
- A project directory where Prosaic can read source artifacts and write generated
  tool files.

Prosaic does not require network access or service credentials at runtime. It
reads local files and writes local files under the project root.

## Install

### From a local clone

```bash
cd prosaic
npm install
npm run build
npm link
prosaic --version
```

`npm link` puts the local `prosaic` executable on your PATH. If you do not want a
global link, run the built CLI directly from this repository:

```bash
node dist/cli/index.js --version
```

### From npm

After the package is published, install it globally:

```bash
npm install -g prosaic
prosaic --version
```

## First Run

The smallest useful run needs:

- one source directory, `.prosaic/`
- one `prosaic.config.yaml`
- at least one target
- at least one source artifact

The example below writes a rule and a command to Claude Code and Cursor.

### 1. Create a project

```bash
mkdir prosaic-demo
cd prosaic-demo
mkdir -p .prosaic/rules .prosaic/commands
```

### 2. Add a rule

Create `.prosaic/rules/style.md`:

```markdown
---
description: Shared writing style for AI tools.
---

Be concise.
Prefer concrete examples.
```

### 3. Add a command

Create `.prosaic/commands/release.md`:

```markdown
---
description: Prepare a release checklist.
---

Create a release checklist for {{args}}.
```

### 4. Add configuration

Create `prosaic.config.yaml`:

```yaml
targets:
  - claude-code
  - cursor
artifactTypes: [rule, command]
lossyPolicy: warn
```

Configuration is optional for defaults, but a first run should name explicit
targets so the generated files are easy to inspect.

Supported config files:

- `prosaic.config.yaml`
- `prosaic.config.yml`
- `.prosaic.yaml`

Common config keys:

| Key | Meaning | Default |
| --- | --- | --- |
| `source` | Source-of-truth directory | `.prosaic` |
| `targets` | `all` or a list of target IDs | `all` |
| `artifactTypes` | Any of `rule`, `skill`, `subagent`, `command` | all four |
| `lossyPolicy` | `warn` or `error` for non-representable intent | `warn` |
| `backupRetention` | Backups retained before overwrites | `3` |

See [Target On-Disk Contracts](docs/target-contracts.md) for target IDs and
their output contracts.

### 5. Preview the write plan

Run the dry run from the project root, the directory containing
`prosaic.config.yaml`:

```bash
prosaic apply --dry-run
```

Expected output for the starter project:

```text
Dry run (apply): 4 create, 0 overwrite, 0 backup, 0 remove, 0 unchanged. 0 files written, 0 files deleted.
create  .claude/commands/release.md [claude-code]
create  .claude/style.md [claude-code]
create  .cursor/commands/release.md [cursor]
create  .cursor/rules/style.mdc [cursor]
```

Dry runs do not write generated files or update the manifest.

### 6. Apply the generated files

```bash
prosaic apply
```

Expected output:

```text
apply: 4 created, 0 overwritten, 0 unchanged, 0 removed, 0 backed up. 4 changed file(s).
```

Expected files:

```text
.claude/commands/release.md
.claude/style.md
.cursor/commands/release.md
.cursor/rules/style.mdc
.prosaic-manifest.json
.prosaic/commands/release.md
.prosaic/rules/style.md
prosaic.config.yaml
```

`.prosaic-manifest.json` records the files Prosaic generated. Keep it if you want
safe `revert` and reconciliation behavior.

### 7. Re-run safely

Run `apply` again after no source changes:

```bash
prosaic apply
```

Expected result:

```text
0 changed file(s)
```

Prosaic is designed to make no-op re-applies byte-identical.

### 8. Revert generated files

Preview removals:

```bash
prosaic revert --dry-run
```

Expected output:

```text
Dry run (revert): 4 remove. 0 files deleted.
remove   .claude/commands/release.md [claude-code]
remove   .claude/style.md [claude-code]
remove   .cursor/commands/release.md [cursor]
remove   .cursor/rules/style.mdc [cursor]
```

Then remove only Prosaic-managed files:

```bash
prosaic revert
```

Expected output:

```text
revert: 4 file(s) removed.
```

Hand-authored files not recorded in `.prosaic-manifest.json` are not deleted.

## Source Artifacts

Prosaic classifies source files by directory or by explicit `type:` frontmatter.

| Type | Default source directory | Typical output |
| --- | --- | --- |
| `rule` | `.prosaic/rules/` | Rules, memories, instructions |
| `command` | `.prosaic/commands/` | Slash commands or command recipes |
| `skill` | `.prosaic/skills/` | Skill bundles with resources |
| `subagent` | `.prosaic/subagents/` | Agent definitions with resources |

Skills and subagents can include bundled resource files. Prosaic rewrites
internal references when distributing the bundle so generated outputs do not
point back to stale source paths.

## Command Reference

```bash
prosaic apply
prosaic apply --dry-run
prosaic apply --targets claude-code cursor
prosaic apply --types rule command
prosaic apply --source ./ai-artifacts
prosaic apply --lossy error

prosaic revert
prosaic revert --dry-run
prosaic revert --targets cursor
```

CLI flags override `prosaic.config.yaml` for that run.

## Safety Model

- **Contained writes:** every write and delete is confined to the project root;
  symlink escapes are refused.
- **Backups before overwrite:** existing target files are backed up before
  Prosaic overwrites them.
- **Manifest-based revert:** `revert` removes only files recorded in
  `.prosaic-manifest.json`; a missing or corrupt manifest aborts deletion.
- **Idempotent output:** repeated applies over unchanged sources produce
  byte-identical files and `0 changed file(s)`.
- **No silent loss:** lossy or skipped transformations emit warnings naming the
  artifact and target. Use `--lossy error` to fail instead of warning.

## Troubleshooting

### `Dry run (apply): 0 create`

Check that you ran Prosaic from the project root. Prosaic discovers
`prosaic.config.yaml` and `.prosaic/` relative to the current working directory.

Also check that your config selects at least one target and one artifact type.
`targets: []` is a valid no-op.

### `Unknown target`

The target ID in `prosaic.config.yaml` or `--targets` is not registered. Check
[Target On-Disk Contracts](docs/target-contracts.md) or
`src/registry/adapters/contract-matrix.md` for known IDs.

### Revert refuses to run

`revert` requires a valid `.prosaic-manifest.json`. If the manifest is missing or
corrupt, Prosaic aborts instead of guessing which files it owns. Restore the
manifest, or remove generated files manually after reviewing them.

### Generated files overwrite something important

Prosaic backs up files before overwriting them. Review the backup files in the
project root and restore the one you need. Set `backupRetention` higher if you
want to keep more overwrite history.

### Lossy transform warnings

Some targets cannot represent every neutral frontmatter key. With
`lossyPolicy: warn`, Prosaic writes the file and reports the dropped intent. With
`lossyPolicy: error` or `--lossy error`, the run fails instead.

## Develop Prosaic

From this repository:

```bash
npm install
npm run build
npm test
npm run lint
```

Focused test files can be passed through Jest:

```bash
npm test -- tests/e2e/perf-100x30.test.ts
npm test -- tests/e2e/cross-env-byte-identity.test.ts
npm test -- tests/e2e/deterministic-render.test.ts
```

Main source directories:

- `src/cli/` - CLI entry point and argument handling
- `src/config/` - config loading, defaults, and CLI overrides
- `src/discovery/` - source artifact discovery and classification
- `src/pipeline/` - transformation stages
- `src/registry/` - target descriptors and conformance status
- `src/lifecycle/` - apply, dry-run, reconcile, and revert flows
- `src/write/` - guarded filesystem, containment, and backups

## Add or Update a Target

Targets are declarative adapter descriptors plus conformance fixtures. Start
with [Adding a Target](docs/add-a-target.md), then review
[Target On-Disk Contracts](docs/target-contracts.md).

## Performance and Verification

The delivery benchmark distributed 100 artifacts across 30 targets in about
816 ms, under the 30 second threshold. Deterministic rendering and
cross-environment byte identity are covered by the test commands above.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.
