"""Middleware."""
from asyncio import wait_for
from typing import Awaitable, Any, Callable
from jhalog import AsyncLogger, LogEvent
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR


class JhalogMiddleware:
    """Jhalog Middleware.

    Args:
        app: Starlette/FastAPI Application.
        backend: Backend to use.
        request_timeout: Request timeout in seconds. 0 to disable timeout.
            Raises 504 HTTP error is reached. Default to 50 seconds (less to the default
            60s values used in most load balancers and reverse proxies to ensure the
            504 error is risen by the server en properly logged).
        ignore_paths: Paths to do not log.
        forward_request_id: If Set to True, forward the request "X-request-ID"
            header to the "id" log event field and the "X-request-ID" response
            header. A random value is generated if this option is False
            or if the request does not contain the "X-request-ID" header.
        kwargs: Extra jhalog.Logger parameters, like _backends specific parameters.
    """

    __slots__ = ["_logger", "_request_timeout", "_forward_request_id"]

    def __init__(
        self,
        app: Starlette,
        backend: str = "logging",
        *,
        request_timeout: int = 50,
        forward_request_id: bool = True,
        **kwargs: Any
    ) -> None:
        self._request_timeout = request_timeout if request_timeout > 0 else None
        self._logger = AsyncLogger(backend=backend, exception_hook=True, **kwargs)
        self._forward_request_id = forward_request_id

        app.router.on_startup.insert(0, self._logger.__aenter__)
        app.add_event_handler("startup", self._logger.emit_startup_completed_event)
        app.add_event_handler("shutdown", self._logger.__aexit__)
        app.add_middleware(BaseHTTPMiddleware, dispatch=self._middleware_dispatch)
        app.add_exception_handler(Exception, self._server_error_response)

    async def _middleware_dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """HTTP Middleware dispatch function.

        Args:
            request: Request.
            call_next: Returns response based on request.

        Returns:
            Response.
        """
        with self._logger.create_event(
            method=request.method,
            path=request.url.path,
            user_agent=request.headers.get("User-Agent"),
            id=(
                request.headers.get("X-request-ID")
                if self._forward_request_id
                else None
            ),
        ) as event:
            try:
                event.client_ip = request.scope["client"][0]
            except TypeError:
                pass

            try:
                response = await wait_for(call_next(request), self._request_timeout)

            except Exception as exc:
                status, message = event.status_code_from_exception(exc)
                if status == HTTP_500_INTERNAL_SERVER_ERROR:
                    raise
                return PlainTextResponse(message, status, {"X-request-ID": event.id})

            response.headers["X-request-ID"] = event.id
            event.status_code = response.status_code
            return response

    @staticmethod
    async def _server_error_response(*_: Any) -> Response:
        """Return internal server error.

        Returns:
            Response.
        """
        return PlainTextResponse(
            "Internal Server Error",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            headers={"X-request-ID": LogEvent.from_context().id},
        )
