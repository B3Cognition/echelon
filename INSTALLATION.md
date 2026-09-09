# Installation Guide

## Prerequisites

**uv** and Git are required. Install the AI coding CLI you plan to use before agent-backed
commands. Node.js with npm is optional: without it, the core CLI works but
Context7, CodeGraph, and PerlGraph evidence integrations are unavailable.
Docker or Podman is needed only for the default Phase B delivery sandbox.

Install uv if you don't have it:

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

The default installer:

1. Creates a venv at `~/.echelon/venv/` and installs the core Echelon and understanding CLIs, including delivery/harness subcommands
2. When Node.js and npm are available, installs the pinned Prosaic, Context7, CodeGraph, and PerlGraph runtimes under `~/.echelon/node/`
3. Adds `~/.echelon/venv/bin` to your PATH
4. Creates `~/.echelon/memory/` and caches the MemPalace embedding model (~80MB, one time)

SOAR execution is disabled pending removal. `--with-codegen` is rejected before
installation begins. Existing SOAR files are left untouched; Echelon will not
execute them. Shared MemPalace functionality remains installed.

Set `ECHELON_HOME` before installation to relocate the shared Node runtimes. A
complete project-deployed runtime takes precedence when present; otherwise
Echelon's wrappers and harness commands use `${ECHELON_HOME:-$HOME/.echelon}/node`.
Agents call those stable wrappers and commands and do not invoke runtime files
directly.

---

## Initialize a workspace

```bash
cd ~/work/my-project
echelon workspace init --llm claude
```

The normal Echelon installer installs the pinned Prosaic CLI into Echelon's
managed Node runtime. Workspace initialization stages the Echelon-owned package
sources under `.echelon/packages/` and uses that CLI to deploy:

```text
.echelon/prosaic/   # neutral commands and subagents
.echelon/runtime/   # workflow, templates, scripts, config, and stacks
```

Echelon creates a temporary Prosaic package config only for deployment and
removes it afterwards; a workspace that already owns a root
`prosaic.config.yaml`, `prosaic.config.yml`, or `.prosaic.yaml` is left
unchanged and the command stops with an actionable error. For an old Spec-Kit
workspace, run the one-shot `echelon workspace migrate-to-prosaic` importer
before the normal `echelon workspace init` command. After migration, normal
Echelon operation uses canonical `.echelon`, `runs/`, and `specs/` surfaces; it
does not fall back to the legacy tree.

---

## Verify Installation

```bash
# Check core CLIs are on PATH (may need a terminal restart after install)
echelon --help
echelon delivery --help
understanding version
prosaic --version

# Check shared memory stores (no SOAR)
python -m codegen.cli.codegen_cli memory status

# Validate the workspace runtime contract
echelon workspace doctor
```

---

## Per-project setup: wing provisioning

`echelon workspace init` sets up a project for regular Echelon use. Among other things, it provisions the **MemPalace wing** — your project's stable identity in the shared memory store — and writes it to `.echelon/config.yml`.

```bash
cd ~/my-project
echelon workspace init
```

`echelon workspace init` will prompt:

```text
Wing name for MemPalace memory [my-project]: ▌
```

Press Enter to accept the auto-suggestion (derived from your git remote URL, e.g. `my-app` from `github.com/org/my-app`) or type a custom name. The wing is written to `.echelon/config.yml` under `mempalace.wing` and committed with your project.

**Wing rules:**

- Set it once, never change it for a given repo
- All clones of the same repo should use the same wing (they inherit it automatically via `.echelon/config.yml`)
- Two different repos must use different wings — `echelon workspace init` warns you if a collision is detected

Re-running `echelon workspace init` on an already-configured project is safe — if the wing is already set, the step is skipped.

---

## Mine requirements into MemPalace

After `echelon workspace init`, mine your spec files so shared memory utilities can retrieve requirements semantically:

```bash
# Mine a single spec file
python -m codegen.cli.codegen_cli requirements mine specs/spec.md

# Mine all specs matching a glob
python -m codegen.cli.codegen_cli requirements mine "specs/*.md"

# Search what was mined
python -m codegen.cli.codegen_cli requirements search "user authentication" --wing my-app
```

Requirements are parsed by ID (`FR-xxx`, `NFR-xxx`, `AC-xxx`, `ADR-xxx`, `US-xxx`). Documents without explicit IDs are chunked by heading and stored in the `uncategorised` room.

To remove stale drawers (e.g. after re-specifying):

```bash
# Preview
python -m codegen.cli.codegen_cli requirements clean --from-wing my-app --project-dir . --dry-run

# Delete
python -m codegen.cli.codegen_cli requirements clean --from-wing my-app --project-dir .
```

---

## Upgrade

```bash
cd ~/echelon && git pull
bash ~/echelon/scripts/install.sh   # re-runs installer; SOAR skipped if already present, venv rebuilt
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
# Remove the Echelon venv, SOAR, shared Node runtimes, and PATH entries.
# Memory is preserved unless explicitly purged.
bash ~/echelon/scripts/uninstall.sh

# To also delete memory stores (~/.echelon/memory/ and ~/.mempalace/)
bash ~/echelon/scripts/uninstall.sh --purge-memory

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

### SOAR commands are disabled

This is intentional. Use the default Echelon delivery strategy. Installing a
SOAR binary does not re-enable Echelon's retired execution paths.

### Embedding model download fails

The warmup step requires internet access. If it fails silently, the model downloads on first use instead. No action needed.

### Context7, CodeGraph, or PerlGraph runtime unavailable

Install Node.js and npm, then rerun `bash ~/echelon/scripts/install.sh`. Do not
run `npm ci` inside a project's deployed extension; the installer owns the
shared runtimes and refreshes them from the pinned lockfiles.

### Re-run the installer

The installer is safe to re-run. SOAR is skipped if already present, the venv is
rebuilt, and the MemPalace store is preserved.

---

## System Requirements

- **Python**: 3.11 or higher
- **Node.js with npm**: optional; enables Context7, CodeGraph, and PerlGraph
- **Docker or Podman**: needed for default delivery sandbox verification
- **SOAR**: disabled pending removal; no installation option is supported
