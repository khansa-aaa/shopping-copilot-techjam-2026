from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .marketplaces import MARKETPLACES
from .service import MAX_TURNS, ServiceError, ShoppingService


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPOSITORY_ROOT / "data" / "catalog.jsonl"
DEFAULT_STATIC = REPOSITORY_ROOT / "demo" / "web" / "dist"
MAX_BODY_BYTES = 16 * 1024


def _apply_security_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


class CreateSessionRequest(BaseModel):
    request_id: UUID
    mode: Literal["hybrid", "offline"] = "hybrid"
    marketplace: str = "SG"
    preference_tags: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("marketplace")
    @classmethod
    def validate_marketplace(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in MARKETPLACES:
            raise ValueError("unsupported marketplace")
        return normalized

    @field_validator("preference_tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            cleaned = " ".join(value.split()).strip()
            if not cleaned or len(cleaned) > 40:
                raise ValueError("preference tags must be 1 to 40 characters")
            if cleaned.casefold() not in {item.casefold() for item in result}:
                result.append(cleaned)
        return result


class MessageRequest(BaseModel):
    request_id: UUID
    message: str = Field(min_length=1, max_length=1000)
    expected_turn: int = Field(ge=1, le=MAX_TURNS)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if not cleaned:
            raise ValueError("message cannot be blank")
        return cleaned


def create_app(
    *,
    service: ShoppingService | None = None,
    static_directory: Path | None = None,
    initialize_in_background: bool = True,
) -> FastAPI:
    shopping_service = service or ShoppingService(os.environ.get("SHOPPING_COPILOT_CATALOG", DEFAULT_CATALOG))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task: asyncio.Task | None = None
        if initialize_in_background and shopping_service.status != "ready":
            task = asyncio.create_task(asyncio.to_thread(shopping_service.initialize))
        yield
        if task is not None and not task.done():
            task.cancel()

    app = FastAPI(
        title="Shopping Copilot local experience",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.shopping_service = shopping_service
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
            return _apply_security_headers(
                JSONResponse(
                    status_code=413,
                    content={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request bodies are limited to 16 KB."}},
                )
            )

        # Content-Length can be omitted or malformed.  The local API accepts only
        # small JSON payloads, so verify the bytes FastAPI will actually parse too.
        if len(await request.body()) > MAX_BODY_BYTES:
            return _apply_security_headers(
                JSONResponse(
                    status_code=413,
                    content={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request bodies are limited to 16 KB."}},
                )
            )
        response = await call_next(request)
        return _apply_security_headers(response)

    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError):
        headers = {"Retry-After": "2"} if exc.status_code == 503 else None
        return JSONResponse(status_code=exc.status_code, content=exc.payload(), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(part) for part in item.get("loc", [])[1:]), "message": item.get("msg", "Invalid value")}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": "Check the request fields.", "fields": errors}},
        )

    @app.get("/api/health")
    async def health():
        return await asyncio.to_thread(shopping_service.health)

    @app.post("/api/sessions", status_code=201)
    async def create_session(payload: CreateSessionRequest):
        return await asyncio.to_thread(
            shopping_service.create_session,
            payload.request_id.hex,
            mode=payload.mode,
            marketplace=payload.marketplace,
            preference_tags=payload.preference_tags,
        )

    @app.post("/api/sessions/{session_id}/messages")
    async def message(session_id: str, payload: MessageRequest):
        if len(session_id) != 32:
            raise ServiceError(404, "SESSION_NOT_FOUND", "This shopping session is no longer available. Start a new one.")
        return await asyncio.to_thread(
            shopping_service.respond,
            session_id,
            request_id=payload.request_id.hex,
            message=payload.message,
            expected_turn=payload.expected_turn,
        )

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        await asyncio.to_thread(shopping_service.delete_session, session_id)
        return Response(status_code=204)

    static_path = static_directory or DEFAULT_STATIC
    if static_path.is_dir():
        app.mount("/", StaticFiles(directory=static_path, html=True), name="web")

    return app


app = create_app()
