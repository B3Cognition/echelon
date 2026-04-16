"""
SOAR SML Bridge for /codegen pipeline.
Spec 008: SOAR-Powered Claude Code Software Development Agent.

Two execution models:
  Model A: Persistent SOAR daemon process (preferred, lower latency).
  Model B: Per-phase SOAR invocation with serialized WM state file (fallback).
"""

from .soar_bridge import SOARBridge, SOARBridgeModel, WMEInjectionResult

__all__ = ["SOARBridge", "SOARBridgeModel", "WMEInjectionResult"]
__version__ = "1.0.0"
