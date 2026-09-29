"""Compatibility import for the extracted Prosaic runtime implementation."""
import sys
from prosaic_runtime import openai_compatible_filters as _implementation
sys.modules[__name__] = _implementation
