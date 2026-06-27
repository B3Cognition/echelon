# CodeGraph Vendor Provenance

This directory vendors the CodeGraph package used by the reverse-engineering
bridge.

- Package: `@colbymchenry/codegraph`
- Version: `0.7.2`
- Source tarball:
  `https://registry.npmjs.org/@colbymchenry/codegraph/-/codegraph-0.7.2.tgz`
- npm integrity:
  `sha512-m6ALu7iSFYiSL7qe6TqPqqLkWSqU1rgg+S4voqQ4oNy+QFy4t26h61qcPRF+WtqqeAV9HH81dJPsdpeP4c2yZA==`
- License evidence: the vendored `package.json` declares `MIT`.

The runtime bridge imports `./vendor/codegraph/dist/index` through
`extension/scripts/node/re/codegraph-adapter.js`. Do not update the vendored
payload without updating `echelon-vendor.json` and rerunning the CodeGraph
integration contract tests.

`scripts/install.sh` can optionally install the global CodeGraph CLI at version
`1.0.1` for developer use. The RE bridge runtime does not use that global CLI;
it imports the vendored `0.7.2` package recorded here.

The manifest hash covers `package.json` and `dist/**` only. It intentionally
excludes this provenance note and the manifest itself so the verification hash
can remain stable while documenting the payload.
