# Workspace Model

Echelon treats every project as a workspace with zero or more source roots.

- Single repo: `sources: [.]`
- Polyrepo: `sources: [repo-a, repo-b]`
- Planning-only workspace: `sources: []`

The workspace root owns project-visible `specs/` artifacts and local Echelon
runtime state. `.specify/` and `runs/` are runtime directories and should be
gitignored in generated workspaces; published spec artifacts under `specs/`
are the tracked handoff.

For polyrepo work, initialize a lightweight workspace Git repo:

```bash
git init
printf "/og-platform/\n/pbg-api/\n/.specify/\n/runs/\n" >> .gitignore
git add .gitignore specs
git commit -m "chore: initialize echelon workspace"
```

For an existing branchless workspace, use the one-time migration script from the workspace root:

```bash
python .specify/extensions/echelon/scripts/python/migrate_workspace_git.py          # dry-run plan
python .specify/extensions/echelon/scripts/python/migrate_workspace_git.py --write  # git init, update .gitignore, stage specs
python .specify/extensions/echelon/scripts/python/migrate_workspace_git.py --commit # also commit staged workspace files
```

The script stages only `.gitignore` and `specs`. Detected source roots,
`.specify/`, and `runs/` are added to `.gitignore` before staging so runtime
state and implementation repositories are not committed into the lightweight
workspace Git repo.

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
echelon harness run 001-feature
```

Use the source path in `echelon spec target`. A source id may be displayed for readability, but the stored target is the path relative to the workspace root.
