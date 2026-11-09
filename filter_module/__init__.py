"""Causal real-time EMG filter (Rust extension).

Public API is re-exported from the compiled ``_filter_module`` extension, so
``import filter_module`` keeps working exactly as before.
"""

from ._filter_module import (  # noqa: F401
    StreamingFilter,
    __version__,
    apply_filter,
    process_array,
)

__all__ = ["apply_filter", "process_array", "StreamingFilter", "__version__"]
