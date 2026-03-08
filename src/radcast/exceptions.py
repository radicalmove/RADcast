"""Custom exceptions for RADcast runtime."""

from __future__ import annotations


class JobCancelledError(RuntimeError):
    """Raised when an enhancement job is cancelled."""


class EnhancementRuntimeError(RuntimeError):
    """Raised when the enhancement engine fails."""
