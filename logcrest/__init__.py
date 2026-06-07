# Expose primary interface for external use
from .decorator import log_decorator, DEBUG, INFO, WARNING, ERROR, CRITICAL
from .flow import log_flow
from .utils import log, configure


def instrument(app, **middleware_kwargs):
    """Attach LogCrestMiddleware to a FastAPI / Starlette app in one call.

    Equivalent to:
        from logcrest.integrations.fastapi import LogCrestMiddleware
        app.add_middleware(LogCrestMiddleware, **middleware_kwargs)

    Returns the app so the call can be chained.
    """
    from .integrations.fastapi import LogCrestMiddleware
    app.add_middleware(LogCrestMiddleware, **middleware_kwargs)
    return app
