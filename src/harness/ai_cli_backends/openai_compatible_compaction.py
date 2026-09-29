"""Compatibility import for the extracted Prosaic runtime implementation."""
import sys
from prosaic_runtime import openai_compatible_compaction as _implementation
sys.modules[__name__] = _implementation
