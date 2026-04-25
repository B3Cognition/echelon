#!/bin/bash
# Emits >10MB of output to test buffer truncation
# Used by SYS-07 buffer tests

# Generate ~11MB of output (11 * 1024 * 1024 bytes)
dd if=/dev/zero bs=1024 count=11264 2>/dev/null | tr '\0' 'A'
