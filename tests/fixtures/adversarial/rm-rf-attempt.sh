#!/bin/bash
# Attempts destructive operations to test sandbox containment (SYS-06)
# This should only damage the bind-mounted worktree, not the host

rm -rf /workspace/* 2>/dev/null || true
rm -rf /tmp/* 2>/dev/null || true
echo "Destruction attempted"
