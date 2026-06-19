# Workspace Model

Echelon treats every project as a workspace with zero or more source roots.

- Single repo: `sources: [.]`
- Polyrepo: `sources: [repo-a, repo-b]`
- Planning-only workspace: `sources: []`

The workspace root owns `.specify/`, `specs/`, `runs/`, and Echelon state. Source roots own implementation files.

For polyrepo work, initialize a lightweight workspace Git repo:

```bash
git init
printf "/og-platform/\n/pbg-api/\n/runs/build-*/\n/runs/verify-*/\n" >> .gitignore
git add .gitignore .specify specs
git commit -m "chore: initialize echelon workspace"
```

For an existing branchless workspace, use the one-time migration script from the workspace root:

```bash
python .specify/extensions/echelon/scripts/python/migrate_workspace_git.py          # dry-run plan
python .specify/extensions/echelon/scripts/python/migrate_workspace_git.py --write  # git init, update .gitignore, stage workspace files
python .specify/extensions/echelon/scripts/python/migrate_workspace_git.py --commit # also commit staged workspace files
```

The script stages only `.gitignore`, `.specify`, and `specs`. Detected source roots are added to `.gitignore` before staging so implementation repositories are not committed into the lightweight workspace Git repo.

When running from an Echelon source checkout instead of an installed workspace extension, pass the target workspace explicitly:

```bash
python scripts/python/migrate_workspace_git.py /path/to/workspace --write
```

Do not use a branchless workspace for new runs. Echelon only allows branchless workspaces for legacy recovery.

When a workspace has multiple source roots, select the implementation target before harness build:

```bash
echelon spec target 001-feature og-platform
echelon harness run 001-feature
```

Use the source path in `echelon spec target`. A source id may be displayed for readability, but the stored target is the path relative to the workspace root.
