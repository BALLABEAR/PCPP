"""
Backward-compatible flow exports.

New implementations are split one-flow-per-file under flows/.
"""

from flows.flows_registry import get_registered_flows

# Backward-compatible module-level exports are generated from one source of truth.
_REGISTERED = get_registered_flows()
globals().update(_REGISTERED)
__all__ = sorted(_REGISTERED.keys())
