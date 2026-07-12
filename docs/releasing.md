# Releasing Echelon

Echelon releases are GitHub Releases only. The release workflow builds and uploads Python package artifacts to the GitHub Release; it does not publish to PyPI.

## Version Policy

Release versions always move to the next higher minor-boundary version:

- `3.0.81` releases as `3.1.0`
- `3.1.5` releases as `3.2.0`
- `3.9.6` releases as `4.0.0`

Do not create patch release tags. Release tags must be shaped as `vMAJOR.MINOR.0`.

## Prepare the Release Commit

Preview the computed release version:

```bash
python scripts/prepare-release.py --dry-run
```

Apply the version bump:

```bash
python scripts/prepare-release.py
```

Review and test the changed metadata:

```bash
git diff
.venv/bin/python -m pytest tests/unit/test_prepare_release.py tests/unit/test_version_metadata.py -q
```

Commit and push the release prep commit:

```bash
git add pyproject.toml uv.lock README.md extension/extension.yml src/echelon/cli.py
git commit -m "chore: release v<computed-version>"
git push origin main
```

## Wait for CI

Before tagging, wait until the existing GitHub CI workflow is green for the release prep commit on `main`.

The release workflow checks these CI jobs on the exact tagged commit:

- `Shell tests (unit + integration + e2e + validation)`
- `Python unit tests`

If either check is missing, pending, or failed, the release workflow stops before building artifacts or creating a GitHub Release.

## Tag the Release

After CI is green for the release prep commit, tag that same commit:

```bash
git tag v<computed-version>
git push origin v<computed-version>
```

The tag push starts `.github/workflows/release.yml`. The workflow validates the tag and metadata, verifies the CI gate, builds `dist/*`, creates a GitHub Release with generated notes, and uploads the package artifacts.

## Failed Release Workflow

Open the failed `Release` workflow run in GitHub Actions and inspect the failed step:

- `Validate release tag and metadata`: tag shape or version metadata drift is wrong.
- `Require green CI for tagged commit`: CI was not green for the tagged commit. Wait for CI on `main` to pass, then re-run the release workflow.
- `Build package artifacts`: package metadata or build configuration failed.
- `Create GitHub Release`: GitHub release creation or artifact upload failed.

Do not move the tag to another commit unless the release prep commit itself is wrong. Prefer fixing the release prep commit on `main`, waiting for CI, and creating a new release tag.
