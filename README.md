![Tests](https://github.com/JGoutin/starlette-jhalog/workflows/tests/badge.svg)
[![codecov](https://codecov.io/gh/JGoutin/starlette-jhalog/branch/main/graph/badge.svg)](https://codecov.io/gh/JGoutin/starlette-jhalog)
[![PyPI](https://img.shields.io/pypi/v/starlette-jhalog.svg)](https://pypi.org/project/starlette-jhalog)

# Jhalog (JSON HTTP Access Log) - Starlette/FastAPI middleware

Starlette/FastAPI middleware to add [Jhalog](https://github.com/JGoutin/jhalog-spec)
(JSON HTTP Access Logs) access log on each request.

This middleware is intended to be easy to use and powerful.

Easy to use:
* Integration boilerplate reduced to the minimum.
* Automatically handle common tasks for you:
  * Automatic request ID generation (and `X-Request-ID` headers).
  * Autofill common log event fields like `client_user_agent` and `client_ip`.
  * Request timeout.
  * Unhandled exception handler with proper return code.

Powerful:
* Easy modification the log event fields from anywhere in the route code.
* Support all logging backends from 
  [Jhalog-Python](https://github.com/JGoutin/jhalog-python) 
  (Like Python standard library logging, AWS Cloudwatch Logs, ...)
* Log events flushing is done in background, there is almost no extra overhead on the 
  requests itself.

## Usage

### Installation

The middleware library is available on PyPI and can be installed with pip as follows:

```bash
pip install starlette_jhalog

# Eventually, also install the required backend with the Jhalog library
pip install jhalog[cloudwatch_logs]
```

### Integration with the Starlette/FastAPI application

To integrate the middleware, just initialize the `starlette_jhalog.JhalogMiddleware`
after you Starlette/FastAPI application creation and all other event handlers and 
middlewares registration:

```python
import fastapi
import starlette_jhalog

app = fastapi.FastAPI()

@app.on_event("startup")
async def startup():
    """Initialize database connection."""
    # [...]

@app.on_event("shutdown")
async def shutdown():
    """Terminate database connection."""
    # [...]

# Middleware creation. Require to be initialized after all "@app.on_event()"
starlette_jhalog.JhalogMiddleware(app)
```

> **Note:**
> The order is important because, the middleware register itself with some event
> handlers to the application and ensure that:
> * The logging backend is started before all startup event handlers.
> * The `startup` log event is emitted after all startup event handlers.
> * The `shutdown` log event is emitted after all shutdown event handlers.
> * The logging backend is properly terminated and all log event flushed before 
>  terminating the application.

The middleware is ready and the logging is enabled on all requests.

#### Middleware parameters

In addition to the Starlette/FastAPI Application, the middleware supports various 
optional parameters:

* `backend`: By default, the `logging` standard library is used as backend, but it is
  possible to use any backend supported by the Jhalog library.
* `forward_request_id`: If set to `True` (The default), use the request `X-request-ID`
  header value as `id` log event field is any. Else generate a `id` normally.
  Disabling the request ID forwarding can be helpful on public servers to keep control
  on the value.
* `ignore_paths`: Paths to ignore in logs. Event logs are not emitted at all for
  these paths. This can be used, for instance, to ignore health check from a load 
  balancer and reduce the total of emitted log events (That may have cost impact in 
  Cloud environments).
* `ip_addresses_allowed`: If set to `True`, allow IP addresses in log events. This 
  allows the middleware to set the `client_ip` field. Default to `False` for privacy 
  compliance.
* `request_timeout`: Request timeout in seconds. 0 to disable timeout.
  Default to 50 seconds.
* `server_version`: Value to set to the `server_version` field in the startup log event.
  The value should be the version of your application.

In addition, all parameters from the `jhalog.AsyncLogger` class are supported, including
backend specific parameters.

### Log events details

#### Access log event

Automatic generated for each request, with following fields:

 * `client_ip`: The client IP address. Added only if `ip_addresses_allowed=True` is
   passed on middleware creation. If the [Uvicorn](https://www.uvicorn.org)
   `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` is installed the 
   `X-Forwarded-For` request header will be
   properly handled.
 * `client_user_agent`: User agent from the request `User-Agent` header.
 * `date`: Date and time of the request (This is the time when the request is received,
   not the date when the response is sent).
 * `error_detail`: In case of unhandled exception during the request, the `error_detail`
   field is automatically set to the exception traceback.
 * `execution_time`: Execution time in seconds between the time when the request is 
   received and the time when the response is sent.
 * `id`: Generated for each request. Always added as `X-Request-ID` response 
   header. If `forward_request_id=True` (The default) is passed on middleware creation,
   use the value from the `X-Request-ID` request header if any instead of generating
   a new value.
 * `level`: Log event level. `info` if `status_code` < 400, else `warning` 
   if `status_code` < 500 else `error`.
   Set to `critical` in case of unhandled exception.
 * `method`: Request HTTP method.
 * `path`: Request path.
 * `server_id`: Server ID, generated by the logging backend.
 * `status_code`: The response status code.
 * `type`: Log event type, always `access`.

##### Request timeout

This middleware include a request timeout.

This timeout is important to ensure the log event is always properly emitted in the case
there is a load balancer or reverse proxy before the server. If the client reach its
timeout before the server Starlette fully cancel the request and don't let the
middleware emit a log event.

Also, it is always a good practice to have a timeout on a web server.

If the timeout is reached, a `504 Gateway Timeout` response is returned by the 
application.

The default value for the timeout is 50s (To be just before the default 60s values of 
most load balancer and reverse proxies). It is possible to define or disable the 
timeout on middleware creation using the `request_timeout` parameter.

##### Modifying access log event fields from routes

It is possible to modify the log event from anywhere inside the route code using the
`jhalog.LogEvent `object:

```python
import fastapi
from jhalog import LogEvent

app = fastapi.FastAPI()

@app.get("/")
def read_root():

    # Getting the access log event from context and using it
    event = LogEvent.from_context()
    event["my_custom_field"] = "hello world"
    event.created.append("hello")
    
    # Directly set some fields to the access log event:
    LogEvent.set_to_context(my_custom_field="hello world", my_other_field="other")
    
    # Directly get a value from the access log event
    request_id = LogEvent.get_from_context("id")
    
    return {"Hello": "World"}
```

This library also provides a `starlette.sexceptions.HTTPException` subclass to set
the `error_detail` field directly when raising exceptions:

```python
import fastapi
from starlette.status import HTTP_401_UNAUTHORIZED
from starlette_jhalog import HTTPException

import my_app

app = fastapi.FastAPI()

@app.get("/auth")
def authenticate(user: str, password: str):

    if not my_app.is_password_valid(user, password):
        # Return a "401 Unautorized" response to the client without detail
        # (This is a common security practice)
        # But, store the error reason in the "error_detail" access log event field. 
        raise HTTPException(
            HTTP_401_UNAUTHORIZED,
            error_detail=f"Invalid password for user: {user}"
        )

    return {"Hello": "World"}
```

##### Error handling and status code

In case of unhandled exception during the request, this middleware use the 
Jhalog-Python handler to determinate the best HTTP code to return.

For instance, timeout errors (Including the request timeout from this middleware) will
automatically return `504 Gateway Timeout`.

Depending on the currently used backend, the handler may detect some other cases and
returns errors like `503 Unavailable` or `429 Too Many Requests` (See the backend
details in Jhalog-Python documentation for more information).

Any other case will return `500 Internal Server Error` as normal.

In any case the `error_detail` field is automatically set to the exception traceback, 
and the `level` field set to `critical`.

#### Startup log event

Generated on server startup (Once the Starlette/FastAPI application is fully
initialized, including startup event handlers), with the following fields:

* `date`: Date and time of the event.
* `level`: Log event level, always `info`.
* `os_uptime`: Time between the host OS start and the process creation.
* `server_id`: Server ID, generated by the logging backend.
* `server_uptime`: Time between the server process creation and the end of the 
  Starlette/FastAPI application initialization.
* `server_version`: Value passed using the `server_version` parameter on middleware
  creation.
 * `type`: Log event type, always `startup`.

#### Shutdown log event

Generated on server shutdown (Once the Starlette/FastAPI application is fully
terminated, including shutdown event handlers), with the following fields:

* `date`: Date and time of the event.
* `level`: Log event level, always `info`.
* `server_id`: Server ID, generated by the logging backend.
* `server_uptime`: Time between the server process creation and the end of the 
  Starlette/FastAPI application termination.
 * `type`: Log event type, always `shutdown`.
