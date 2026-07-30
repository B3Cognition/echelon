"""Compatibility shim for the Echelon spec memory miner.

The implementation lives in :mod:`echelon.spec_memory_miner`. Keep this module
only for legacy imports while older code paths are retired.
"""

from echelon.spec_memory_miner import *  # noqa: F401,F403
