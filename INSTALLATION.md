# Installation Guide

## Prerequisites

**uv** is required. **Node.js with npm** is required for Context7, CodeGraph,
and PerlGraph. Install uv if you don't have it:

```bash
brew install uv          # macOS
curl -LsSf https://astral.sh/uv/install.sh | sh  # other
```

---

## Install

Clone echelon and run the installer:

```bash
git clone https://github.com/B3Cognition/echelon.git ~/echelon
bash ~/echelon/scripts/install.sh
```

The installer does six things automatically:

1. Downloads `SoarSuite_9.6.4-Multiplatform.zip` from GitHub and extracts the SOAR binary for your platform into `~/.echelon/soar/bin/`
2. Adds `~/.echelon/soar/bin` to your PATH
3. Creates a venv at `~/.echelon/venv/` and installs all four CLIs (`echelon`, `harness`, `codegen`, `understanding`) into it
4. Installs the pinned Context7, CodeGraph, and PerlGraph runtimes under `~/.echelon/node/`
5. Adds `~/.echelon/venv/bin` to your PATH
6. Creates `~/.echelon/memory/` and caches the AI embedding model (~80MB, one time)

Set `ECHELON_HOME` before installation to relocate the shared Node runtimes. A
complete project-deployed runtime takes precedence when present; otherwise
Echelon's wrappers and harness commands use `${ECHELON_HOME:-$HOME/.echelon}/node`.
Agents call those stable wrappers and commands and do not invoke runtime files
directly.

---

## Register the spec-kit extension

```bash
specify extension add --dev ~/echelon/extension
```

---

## Verify Installation

```bash
# Check CLIs are on PATH (may need a terminal restart after install)
echelon --help
echelon delivery --help
codegen --help
understanding version

# Check SOAR is on PATH
soar --version

# Check memory stores
codegen memory status

# Validate the extension setup
bash ~/echelon/scripts/bash/dry-run.sh
```

---

## Per-project setup: wing provisioning

`echelon workspace init` sets up a project for codegen use. Among other things, it provisions the **MemPalace wing** — your project's stable identity in the shared memory store — and writes it to `.echelon/config.yml`.

```bash
cd ~/my-project
echelon workspace init
```

`echelon workspace init` will prompt:

```text
Wing name for MemPalace memory [my-project]: ▌
```

Press Enter to accept the auto-suggestion (derived from your git remote URL, e.g. `my-app` from `github.com/org/my-app`) or type a custom name. The wing is written to `echelon-config.yml` under `mempalace.wing` and committed with your project.

**Wing rules:**

- Set it once, never change it for a given repo
- All clones of the same repo should use the same wing (they inherit it automatically via `echelon-config.yml`)
- Two different repos must use different wings — `echelon workspace init` warns you if a collision is detected

Re-running `echelon workspace init` on an already-configured project is safe — if the wing is already set, the step is skipped.

---

## Mine requirements into MemPalace

After `echelon workspace init`, mine your spec files so the codegen RE phase can retrieve requirements semantically:

```bash
# Mine a single spec file
codegen requirements mine specs/spec.md

# Mine all specs matching a glob
codegen requirements mine "specs/*.md"

# Search what was mined
codegen requirements search "user authentication" --wing my-app
```

Requirements are parsed by ID (`FR-xxx`, `NFR-xxx`, `AC-xxx`, `ADR-xxx`, `US-xxx`). Documents without explicit IDs are chunked by heading and stored in the `uncategorised` room.

To remove stale drawers (e.g. after re-specifying):

```bash
# Preview
codegen requirements clean --from-wing my-app --project-dir . --dry-run

# Delete
codegen requirements clean --from-wing my-app --project-dir .
```

---

## Upgrade

```bash
cd ~/echelon && git pull
bash ~/echelon/scripts/install.sh   # re-runs installer; SOAR skipped if already present, venv rebuilt
specify extension update --dev ~/echelon/extension
```

To force a fresh SOAR download:

```bash
rm -rf ~/.echelon/soar
bash ~/echelon/scripts/install.sh
```

To upgrade the MemPalace or understanding model versions, update the relevant URLs in `pyproject.toml` and re-run the installer.

---

## Uninstall

```bash
# Remove all echelon runtime data (SOAR, venv, memory, config) and PATH entries
bash ~/echelon/scripts/uninstall.sh

# To also delete memory stores (~/.echelon/memory/ and ~/.mempalace/)
bash ~/echelon/scripts/uninstall.sh --purge-memory

# Remove the spec-kit extension
specify extension remove echelon
```

---

## Troubleshooting

### `echelon`, `harness`, `codegen` or `understanding` not found after install

The venv bin directory may not be in your PATH yet:

```bash
source ~/.zshrc   # or ~/.bashrc

# Or add it manually
export PATH="$HOME/.echelon/venv/bin:$PATH"
```

### `soar: command not found` after install

```bash
source ~/.zshrc   # or ~/.bashrc

# Or add it manually
export PATH="$HOME/.echelon/soar/bin:$PATH"
```

### Embedding model download fails

The warmup step requires internet access. If it fails silently, the model downloads on first use instead. No action needed.

### Context7, CodeGraph, or PerlGraph runtime unavailable

Install Node.js and npm, then rerun `bash ~/echelon/scripts/install.sh`. Do not
run `npm ci` inside a project's deployed extension; the installer owns the
shared runtimes and refreshes them from the pinned lockfiles.

### Re-run the installer

The installer is safe to re-run. SOAR is skipped if already present; the venv is rebuilt; `memory-config.yml` is left untouched if it exists.

---

## System Requirements

- **Python**: 3.11 or higher
- **Node.js with npm**: required for Context7, CodeGraph, and PerlGraph
- **OS**: macOS (ARM64, x86-64), Linux (x86-64)
- **Disk**: ~500MB for SOAR + ~80MB for embedding model + ~2GB for understanding (torch + spaCy + transformers)
- **spec-kit**: >= 0.4.2
