"""Bounded Git finalization for standalone commands that write durable outputs."""

from pathlib import Path
import logging

from echelon.git_helpers import GitHelperError, run_git
from harness.secret_scan import scan_paths


class OwnedOutputCommit:
    """Capture clean output paths before writing; preserve unrelated staged work."""

    def __init__(self, root: Path, paths: list[Path], message: str, *, preserve_dirty: bool = False):
        self.root = root.resolve()
        self.paths = [p.absolute().relative_to(self.root).as_posix() for p in paths]
        self.message = message
        self.head = ""
        self.branch = ""
        if run_git(self.root, "rev-parse", "--show-toplevel", check=False).returncode:
            return  # File-only workspaces remain supported.
        self.head = run_git(self.root, "rev-parse", "HEAD", check=False).stdout.strip()
        if not self.head or self.head == "HEAD":
            self.head = ""
            return  # Initial setup does not create the user's baseline commit.
        self.branch = run_git(self.root, "symbolic-ref", "--quiet", "HEAD").stdout.strip()
        self._validate_paths()
        dirty = run_git(self.root, "status", "--porcelain", "--untracked-files=all", "--", *self.paths).stdout
        if dirty.strip():
            if preserve_dirty:
                logging.getLogger(__name__).warning(
                    "Existing edits overlap setup outputs; automatic commit skipped: %s", dirty.strip()
                )
                self.head = ""
                return
            raise GitHelperError("Commit or resolve existing output edits before regeneration:\n" + dirty)

    def commit(self) -> None:
        if not self.head:
            return
        self._validate_paths()
        if (run_git(self.root, "rev-parse", "HEAD").stdout.strip() != self.head
                or run_git(self.root, "symbolic-ref", "--quiet", "HEAD").stdout.strip() != self.branch):
            raise GitHelperError("Workspace HEAD changed during output generation; outputs retained for recovery")
        dirty = run_git(self.root, "status", "--porcelain", "--untracked-files=all", "--", *self.paths).stdout
        if not dirty.strip():
            return
        scan = scan_paths(self.root / path for path in self.paths if (self.root / path).is_file())
        if not scan.ok:
            raise GitHelperError("Output commit blocked: " + scan.format_summary())
        paths = [
            p for p in self.paths
            if (self.root / p).exists() or run_git(self.root, "ls-files", "--", p).stdout.strip()
        ]
        run_git(self.root, "add", "-A", "--", *paths)
        run_git(self.root, "commit", "--only", "-m", self.message, "--", *paths)

    def _validate_paths(self) -> None:
        for path in self.paths:
            current = self.root / path
            while current != self.root:
                if current.is_symlink():
                    raise GitHelperError(f"Refusing symlinked output: {path}")
                current = current.parent
