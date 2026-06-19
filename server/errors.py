"""Unified HTTP error responses."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            error = detail.get("error", str(detail))
            code = detail.get("code", f"HTTP_{exc.status_code}")
        else:
            error = str(detail)
            code = f"HTTP_{exc.status_code}"
        return JSONResponse(status_code=exc.status_code, content={"error": error, "code": code})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "请求参数无效", "code": "VALIDATION_ERROR", "details": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        logging = __import__("logging").getLogger("server")
        logging.exception("未捕获异常: %s", exc.__class__.__name__)
        return JSONResponse(
            status_code=500,
            content={"error": "服务器内部错误", "code": "INTERNAL_ERROR"},
        )
