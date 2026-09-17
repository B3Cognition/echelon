# Verification fixture isolation incident

During repair-refresh convergence, inherited Git repository-selection variables
allowed pre-push verification fixtures to target the calling checkout instead of
their temporary repositories. Fixture commits changed the branch/index and local
Git configuration. This was a verification-boundary failure, not an Echelon
provider or delivery-state change.

Recovery verified that all working files exactly matched checkpoint `11a0bb84`.
The fixture history is retained at `recovery/test-fixture-20260915`; the original
index/config are backed up under `/Users/michalbachorik/work/echelon-recovery.Bu9Pqz`.
The branch and index were restored to the checkpoint without overwriting working
files. Fixture author overrides were removed and `core.bare` restored to false.

The hook now clears Git's documented repository-local environment variables only
in its verification subprocess, for both full and selected verification. Its own
repository checks retain their environment. The standalone shell fixture clears
the same variables before initializing test repositories; its virtualenv-selection
case explicitly clears an inherited `PYTHON` override.

Four regression cases run real Git operations against disposable outer/nested
repositories. They reproduce escaped commits/configuration before the fix and
verify preserved outer HEAD, index and configuration afterward. Together with
seven existing checks, all 11 pass. Shell syntax and whitespace checks pass;
independent read-only review found no blocking issues. This is focused offline
verification, not a full-suite or activation claim. Repair-refresh checkpoint B
remains open and is the next work item.
