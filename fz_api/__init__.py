"""fz-api: HTTP API for the fz parametric scientific computing framework."""

__version__ = "0.1.0"

from .app import create_app  # noqa: E402  (defined after __version__ to avoid cycle)

__all__ = ["create_app", "__version__"]
