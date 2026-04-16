"""
exceptions.py — Security exception types.
Spec 018 T-SEC-2: path traversal and YAML safety.
"""
from __future__ import annotations


class PathTraversalError(Exception):
    """
    Raised when a user-supplied path resolves outside the trusted root.
    Spec 018 RAR-002: path traversal prevention for --anchor and --extract-constitution.

    Attributes:
        supplied_path: the raw path string supplied by the user
        resolved_path: the os.path.realpath()-resolved absolute path
        trusted_root: the trusted root directory boundary
    """

    def __init__(self, supplied_path: str, resolved_path: str, trusted_root: str) -> None:
        self.supplied_path = supplied_path
        self.resolved_path = resolved_path
        self.trusted_root = trusted_root
        super().__init__(
            f"Path traversal detected: '{supplied_path}' resolves to '{resolved_path}', "
            f"which is outside trusted root '{trusted_root}'"
        )


class YamlLoadError(Exception):
    """
    Raised when YAML loading fails structural validation (not a parse error).
    Spec 018 RAR-003: distinguishes schema validation failures from parse errors.
    yaml.YAMLError is still raised for parse errors; this is for post-load validation.
    """

    def __init__(self, file_path: str, reason: str) -> None:
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"YAML load error for '{file_path}': {reason}")
