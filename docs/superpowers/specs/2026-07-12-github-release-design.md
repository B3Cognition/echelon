# GitHub Release Automation Design

Date: 2026-07-12
Status: Approved for planning

## Goal

Echelon needs a repeatable GitHub Release process that publishes release artifacts only after the exact release commit has passed the existing GitHub CI checks. The release process is GitHub-only for this design: it creates GitHub Releases and attaches Python package artifacts, but it does not publish to PyPI.

## Current Context

Echelon is a Python package using `setuptools.build_meta` with static metadata in `pyproject.toml`. The package version is currently repeated in several release-facing surfaces:

- `pyproject.toml`
- `uv.lock`
- `README.md`
- `extension/extension.yml`
- `src/echelon/cli.py`
- `tests/unit/test_version_metadata.py`

The repository already has GitHub CI in `.github/workflows/ci.yml`, running on pushes and pull requests to `main`. Existing tests include `tests/unit/test_version_metadata.py`, which is intended to catch version drift across release metadata.

## Release Version Policy

Every release must bump to the closest higher minor-boundary version:

- `3.0.81` becomes `3.1.0`
- `3.1.5` becomes `3.2.0`
- `3.9.6` becomes `4.0.0`

Patch releases are not produced by this process. A release tag must be shaped as `vMAJOR.MINOR.0`, and the tag version must match the package metadata exactly.

The version bump should be computed from the repository's current package version. Maintainers should not type the target version for the normal release path. Under this policy, Echelon uses single-digit minor release trains; a current version with a minor component greater than `9` is invalid release state and should fail prep.

## Maintainer Workflow

The normal release flow is:

```bash
python scripts/prepare-release.py
git diff
git add pyproject.toml uv.lock README.md extension/extension.yml src/echelon/cli.py tests/unit/test_version_metadata.py
git commit -m "chore: release v<computed-version>"
git push origin main
```

After the push CI for `main` is green, the maintainer tags the same commit:

```bash
git tag v<computed-version>
git push origin v<computed-version>
```

The GitHub release workflow then verifies the tag and CI state before creating a release.

## Components

### `scripts/prepare-release.py`

The prep script computes the next minor-boundary version from `pyproject.toml`, updates all known version surfaces, and validates that they agree after the write.

Expected behavior:

- Read `project.version` from `pyproject.toml`.
- Compute the next release version:
  - if minor is less than `9`, increment minor and set patch to `0`
  - if minor is `9`, increment major and set minor and patch to `0`
  - if minor is greater than `9`, fail because the repository is outside the release policy
- Update all release-facing version surfaces.
- Provide `--dry-run` to print planned changes without writing files.
- Fail if any expected version surface is missing or cannot be updated exactly once.
- Fail if post-update validation finds disagreement across release metadata.

### `.github/workflows/release.yml`

The release workflow runs on pushed tags matching `v*`.

Expected checks before release creation:

- The tag must match `vMAJOR.MINOR.0`.
- The tag version must match `project.version` in `pyproject.toml`.
- The same version must match `extension/extension.yml`, README version text, `CLI_VERSION`, and the version metadata test expectation.
- Required GitHub CI checks for the exact tagged commit must already be successful.

Expected release actions:

- Install Python 3.11.
- Install package build tooling.
- Build `sdist` and `wheel` into `dist/`.
- Create a GitHub Release using the tag.
- Generate release notes from GitHub.
- Upload `dist/*` artifacts to the release.

The workflow must not publish to PyPI.

### `docs/releasing.md`

Release documentation should explain:

- the next-minor-only version policy
- the local prep command
- the need to push the release commit and wait for CI to pass before tagging
- the tag command
- how to inspect a failed release workflow
- that PyPI publishing is intentionally out of scope

## CI Gate Design

The release workflow must verify CI for the exact tagged commit rather than merely re-running a subset of checks inside the release job.

The gate should query GitHub for check runs on `github.sha` and require the repository's CI workflow jobs to have completed successfully before proceeding. If the tag was pushed before CI completed, the release workflow should fail with a clear message instructing the maintainer to wait for CI and re-run the release workflow.

The release workflow may still run fast local validations and package builds after the CI gate passes. Those validations catch packaging-specific issues and metadata drift; they do not replace the required green CI gate.

## Error Handling

Release prep failures should be explicit:

- invalid current version
- missing file
- expected version string not found
- multiple ambiguous matches in a version surface
- post-update version mismatch

Release workflow failures should identify the failed gate:

- malformed tag
- tag and package version mismatch
- metadata version mismatch
- CI checks missing, pending, or failed for the tagged commit
- package build failure
- GitHub Release creation failure

## Testing

Focused automated coverage should include:

- next-minor calculation examples:
  - `3.0.81` to `3.1.0`
  - `3.1.5` to `3.2.0`
  - `3.9.6` to `4.0.0`
- dry-run behavior does not write files
- metadata validation catches mismatched version surfaces
- `tests/unit/test_version_metadata.py` reflects the release version after running the prep script

Manual verification before first release:

```bash
python scripts/prepare-release.py --dry-run
python scripts/prepare-release.py
pytest tests/unit/test_version_metadata.py -q
python -m build
```

The full release still requires green GitHub CI on the release commit before tagging.

## Non-Goals

- PyPI publishing
- automatic commits from GitHub Actions
- workflow-dispatch releases that mutate repository files
- patch-version release tags
- changing the existing CI workflow beyond what is required to identify required checks from the release workflow
