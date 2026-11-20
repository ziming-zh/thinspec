"""ThinSpec: keep a system's abstraction small, visible, and honest while agents write the code."""

__version__ = "0.4.0"


class ThinSpecError(Exception):
    """A user-facing error: bad input, missing node, invalid state transition."""
