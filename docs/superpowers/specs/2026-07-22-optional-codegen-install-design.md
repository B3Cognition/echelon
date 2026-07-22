# Optional SOAR and Codegen Installation

**Date:** 2026-07-22
**Status:** Approved

## Goal

Make the SOAR-backed codegen pipeline an explicit installation option. A plain
Echelon install must not download SOAR, install codegen-only Python dependencies,
create a `codegen` executable, warm the MemPalace embedding model, or modify the
shell PATH for SOAR. Users opt into the complete pipeline with:

```bash
bash scripts/install.sh --with-codegen
```

The installer remains non-interactive and deterministic for local use and CI.

## Installation Contract

`bash scripts/install.sh` installs the core Echelon package and its ordinary
commands, including `echelon`, `understanding`, and the harness functionality.
It skips every codegen-only installation step and prints codegen and SOAR as
not installed, with the exact opt-in command.

`bash scripts/install.sh --with-codegen` additionally:

- installs the codegen dependency extra;
- exposes the standalone `codegen` launcher;
- downloads and installs the pinned SOAR release when absent;
- adds the SOAR binary directory to PATH using the existing idempotent logic;
- creates the codegen memory directory and warms the embedding model; and
- reports the installed SOAR and codegen locations.

Unknown arguments fail before the installer mutates the environment and print
concise usage. `--help` prints the two supported installation forms and exits
successfully without mutation.

Re-running the installer converges to the selected mode. In particular, a
plain install after an opt-in install removes the installer-managed `codegen`
launcher, while leaving user data and downloaded SOAR files intact. It does
not delete caches, memory, or binaries because changing install mode should not
destroy recoverable user state. The completion message makes this distinction
clear.

## Packaging Boundary

Move codegen-only third-party dependencies out of the base dependency list and
into a `codegen` optional dependency group. This group includes MemPalace and
the transitive embedding/ChromaDB stack it provides. Dependencies required by
core Echelon remain in the base group.

Remove the unconditional `codegen` entry point from project metadata. The
installer owns a small launcher in `~/.echelon/venv/bin/codegen` and creates it
only for `--with-codegen`; the launcher invokes
`codegen.cli.codegen_cli:main` with the venv Python. The codegen Python package
may remain in the Echelon wheel as dormant implementation code, but without
its dependencies, launcher, SOAR runtime, and warm-up it is not installed as a
usable pipeline. This avoids a disruptive source-tree split while satisfying
the user-visible installation contract.

Core runtime imports of codegen memory helpers must remain optional and degrade
cleanly when the extra is absent. Existing best-effort imports already follow
this pattern; tests will guard it explicitly. `echelon codegen` and
`strategy=codegen` must fail early with an actionable message directing the
user to rerun the installer with `--with-codegen`, rather than failing later on
a missing module or SOAR executable.

## Installer Structure

Parse arguments at the beginning of `scripts/install.sh`, before tool or
platform checks. Store the selected mode in one installer-specific boolean.
Keep core setup unconditional and wrap these existing sections in the opt-in
branch:

- platform selection needed solely for SOAR;
- SOAR download and PATH setup;
- installation of the `codegen` dependency extra and launcher;
- memory-directory setup; and
- embedding-model warm-up.

The opt-in pip operation installs the local project with its codegen extra. The
default operation installs the local project without that extra and removes
only the launcher managed by this installer. Summary output is derived from
the selected mode, not from unrelated globally available executables.

## Compatibility and Failure Handling

- Existing `--with-codegen` installations retain the current pinned SOAR
  version and paths.
- Existing codegen state, MemPalace data, and downloaded SOAR assets are never
  deleted by a default reinstall.
- The core install must work on a supported Python platform without performing
  SOAR platform validation; SOAR platform validation occurs only after opt-in.
- A failed optional dependency or SOAR installation remains a hard installer
  failure, matching current `set -e` behavior.
- The existing `ECHELON_INSTALL_CODEGRAPH_CLI` option remains independent.

## Documentation

Update the README installation section, CLI table, codegen section, and any
installer comments that claim all CLIs or SOAR are installed unconditionally.
Examples use the plain command for core installation and `--with-codegen` only
where the SOAR pipeline is required.

## Tests

Add shell-level installer contract tests that run against isolated fake HOME,
PATH, `uv`, and download commands so they do not touch the developer machine or
network. Cover:

1. default mode skips SOAR download, codegen extra, launcher creation, memory
   warm-up, and SOAR PATH edits;
2. `--with-codegen` performs all optional steps and creates the launcher;
3. default mode removes only a previously installer-managed launcher;
4. unknown options fail before mutation;
5. `--help` exits without mutation; and
6. completion summaries accurately describe both modes.

Add Python packaging/CLI tests proving that codegen-only dependencies are not
base requirements, the project metadata has no unconditional codegen entry
point, core imports work without MemPalace, and codegen entry paths produce the
actionable opt-in error when unavailable. Run the focused tests first, then the
installer shell tests and the relevant unit suite.

## Out of Scope

- Deleting existing SOAR, MemPalace, or codegen user data during downgrade.
- An interactive installer prompt.
- Changing pipeline behavior for users who opt in.
- Making CodeGraph, PerlGraph, Context7, or understanding optional.
