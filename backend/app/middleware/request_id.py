from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import set_request_id

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Reads X-Request-ID from incoming request headers or generates a new one.
    Attaches it to the response and propagates it via contextvars.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or set_request_id()
        set_request_id(request_id)
        logger.info("-> %s %s", request.method, request.url.path)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info("<- %s %s %s", request.method, request.url.path, response.status_code)
        return response
