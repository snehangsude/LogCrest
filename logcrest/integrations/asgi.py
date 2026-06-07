"""
Framework-agnostic alias for LogCrestMiddleware.

LogCrestMiddleware is pure stdlib ASGI — it works with any ASGI framework
(FastAPI, Starlette, Quart, …) and imports no third-party package. This module
exists so the import path matches the capability:

    from logcrest.integrations.asgi import LogCrestMiddleware

The original `logcrest.integrations.fastapi` path remains valid and points to
the same class.
"""
from .fastapi import LogCrestMiddleware

__all__ = ["LogCrestMiddleware"]
