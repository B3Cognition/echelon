# Optional SOAR and Codegen Installation

**Date:** 2026-07-22
**Status:** Approved

## Goal

Make the SOAR-backed codegen pipeline an explicit installation option. A plain
Echelon install must not download SOAR, create a `codegen` executable, or modify
the shell PATH for SOAR. MemPalace remains a core dependency because ordinary
non-SOAR squad runs use it for contextual retrieval and published-spec mining.
Users opt into the complete SOAR pipeline with:

```bash
bash scripts/install.sh --with-codegen
```

The installer remains non-interactive and deterministic for local use and CI.

## Installation Contract

`bash scripts/install.sh` installs the core Echelon package and its ordinary
commands, including `echelon`, `understanding`, and the harness functionality.
It skips every codegen-only installation step and prints codegen and SOAR as
not installed, with the exact opt-in command. It still creates the shared
memory directory and warms the MemPalace embedding model.

`bash scripts/install.sh --with-codegen` additionally:

- exposes the standalone `codegen` launcher;
- downloads and installs the pinned SOAR release when absent;
- adds the SOAR binary directory to PATH using the existing idempotent logic;
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

Keep MemPalace and its transitive embedding/ChromaDB stack in the base
dependency list. Although its adapters currently live under the `codegen`
Python namespace, MemPalace is shared infrastructure used by both the ordinary
squad path and the SOAR pipeline. This change must not reduce memory behavior
for non-SOAR runs.

Remove the unconditional `codegen` entry point from project metadata. The
installer owns a small launcher in `~/.echelon/venv/bin/codegen` and creates it
only for `--with-codegen`; the launcher invokes
`codegen.cli.codegen_cli:main` with the venv Python. The codegen Python package
may remain in the Echelon wheel as dormant implementation code, but without
its launcher and SOAR runtime it is not installed as a usable pipeline. This
avoids a disruptive source-tree split while satisfying the user-visible
installation contract.

Core runtime imports of codegen memory helpers continue to use the installed
MemPalace integration. Existing best-effort degradation remains intact for
runtime storage errors. `echelon codegen` and
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
- installation of the `codegen` launcher.

The same Python package and dependency set is installed in both modes. The
default operation removes only the launcher managed by this installer. Summary
output is derived from the selected mode, not from unrelated globally available
executables.

## Compatibility and Failure Handling

- Existing `--with-codegen` installations retain the current pinned SOAR
  version and paths.
- Existing codegen state, MemPalace data, and downloaded SOAR assets are never
  deleted by a default reinstall.
- The core install must work on a supported Python platform without performing
  SOAR platform validation; SOAR platform validation occurs only after opt-in.
- A failed Python dependency installation remains a hard installer failure in
  both modes. A failed SOAR installation is likewise fatal after opt-in,
  matching current `set -e` behavior.
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

1. default mode skips SOAR download, launcher creation, and SOAR PATH edits,
   while still installing and warming MemPalace;
2. `--with-codegen` performs all optional steps and creates the launcher;
3. default mode removes only a previously installer-managed launcher;
4. unknown options fail before mutation;
5. `--help` exits without mutation; and
6. completion summaries accurately describe both modes.

Add Python packaging/CLI tests proving that MemPalace remains a base requirement,
the project metadata has no unconditional codegen entry point, non-SOAR memory
integration remains available, and codegen entry paths produce the actionable
opt-in error when unavailable. Run the focused tests first, then the installer
shell tests and the relevant unit suite.

## Out of Scope

- Deleting existing SOAR, MemPalace, or codegen user data during downgrade.
- An interactive installer prompt.
- Changing pipeline behavior for users who opt in.
- Making CodeGraph, PerlGraph, Context7, or understanding optional.
