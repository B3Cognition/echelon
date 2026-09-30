"""Errors raised at the controller-owned delivery boundary."""


class DeliveryConfigurationError(RuntimeError):
    """Delivery cannot run under the active controller contract."""
