# Workspace Model

Echelon treats every project as a workspace with zero or more source roots.

- Single repo: `sources: [.]`
- Polyrepo: `sources: [sources/repo-a, sources/repo-b]`
- Planning-only workspace: `sources: []`

The workspace root owns project-visible `specs/` artifacts and local Echelon
runtime state. `.echelon/config.yml` is the committed project contract.
`.echelon/local.yml`, `.specify/`, `runs/`, `.claude/`, `.echelon/runtime/`,
`.echelon/cache/`, and `.echelon/recovery-backups/` are runtime/local
directories and should be gitignored in generated workspaces; published spec
artifacts under `specs/` are the tracked handoff. New orchestration workspaces
scaffold `sources/README.md` as the visible landing zone for implementation
repositories. Child repositories under `sources/` are ignored by workspace Git
until they are declared as source roots in `.echelon/config.yml`.

For polyrepo work, initialize a lightweight workspace Git repo:

```bash
git init
mkdir -p .echelon specs sources
cat > .echelon/config.yml <<'YAML'
workspace:
  git_role: orchestration
sources:
  - id: og-platform
    path: sources/og-platform
  - id: pbg-api
    path: sources/pbg-api
YAML
printf "/sources/*\n!/sources/README.md\n/.specify/\n/runs/\n/.claude/\n/.echelon/runtime/\n/.echelon/cache/\n/.echelon/recovery-backups/\n" >> .gitignore
printf "# Workspace Source Roots\n\nClone implementation repositories here and declare them in .echelon/config.yml.\n" > sources/README.md
git add .gitignore .echelon/config.yml specs sources/README.md
git commit -m "chore: initialize echelon workspace"
```

For an existing branchless or legacy-config workspace, use the workspace command
from the workspace root:

```bash
echelon workspace doctor
echelon workspace migrate          # dry-run plan
echelon workspace migrate --write  # git init, copy legacy config, update .gitignore, stage specs/config
echelon workspace migrate --commit # also commit staged workspace files
```

The migration stages only workspace-contract files: `.gitignore`,
`.echelon/config.yml`, and `specs/`. Detected source roots, `.specify/`,
`runs/`, `.claude/`, `.echelon/runtime/`, `.echelon/cache/`, and
`.echelon/recovery-backups/` are added to `.gitignore` before staging so runtime
state and implementation repositories are not committed into the lightweight
workspace Git repo. If legacy
`.specify/extensions/echelon/echelon-config.yml` exists and `.echelon/config.yml`
does not, migration copies it to the canonical path.

When running from an Echelon source checkout instead of an installed workspace extension, pass the target workspace explicitly:

```bash
python scripts/python/migrate_workspace_git.py /path/to/workspace --write
```

For an existing single Git repository that mixes Echelon orchestration artifacts and implementation source files at the root, use the source split migration:

```bash
python scripts/python/split_workspace_source_repo.py /path/to/workspace --source-dir source          # dry-run plan
python scripts/python/split_workspace_source_repo.py /path/to/workspace --source-dir source --write  # move source files, create source/.git, stage root split
```

The splitter keeps `.specify`, `specs`, `runs`, and root `.gitignore` at the workspace root. It moves implementation files into the child source directory, initializes a child Git repository there, copies the original `.gitignore` into that child repository, and stages the root repository deletions plus `/source/` ignore entry. Commit the root workspace after verifying the child source repo builds.

Do not use a branchless workspace for new runs. Echelon only allows branchless workspaces for legacy recovery.

When a workspace has multiple source roots, select the implementation target before harness build:

```bash
echelon spec target 001-feature og-platform
echelon delivery run 001-feature
```

Use the source path in `echelon spec target`. A source id may be displayed for readability, but the stored target is the path relative to the workspace root.

For a new implementation repo, let Echelon prepare the target directory, Git
repository, initial commit, and feature branch:

```bash
echelon spec target 001-feature sources/new-tool --init
echelon delivery run 001-feature --mode=banzai
```
