"""FastAPI service. The web app talks only to this."""

import time
import uuid
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.errors import acceptable_request_id, install_error_handlers, internal_error
from api.openapi import error_responses, install_openapi, ok
from api.routes import router
from rag import index
from rag import search as rag_search
from rag.config import data_source, database_url, rerank_enabled

VERSION = "0.0.0"
REQUIRED_EXTENSIONS = {"vector", "pg_search"}
CORS_ORIGINS = ["http://localhost:3000", "http://localhost:3100"]

DESCRIPTION = """
Ask questions of UK–ECHR case law; every claim cites the exact paragraph.

Every response carries `X-Request-ID` and `Server-Timing`. Every error has the `ApiError` shape
(`error`, `detail`, `request_id`). Request and response shapes are the project's API contract
(`packages/contract`), and the examples below come from its fixtures.

Demo path: `POST /ask` → `GET /case/{item_id}` (open a cited paragraph) → `POST /search`
(compare modes) → `GET /stats`.
"""


def _load_models(app: FastAPI) -> None:
    """Load the embedder and reranker once, so no request pays the model start-up cost."""
    app.state.embedder = index.get_embedder()
    app.state.reranker = rag_search.get_reranker() if rerank_enabled() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.embedder = None
    app.state.reranker = None
    _load_models(app)
    yield


app = FastAPI(
    title="echr-lookup API",
    version=VERSION,
    description=DESCRIPTION,
    lifespan=lifespan,
)
install_error_handlers(app)
install_openapi(app, router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an id and a timing, and turn bugs into a contract-shaped 500."""
    request.state.request_id = (
        acceptable_request_id(request.headers.get("x-request-id")) or f"req-{uuid.uuid4().hex[:16]}"
    )
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        response = internal_error(request, exc)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Server-Timing"],
)

app.include_router(router)


@app.get(
    "/health",
    response_model=None,
    summary="Service and database status (contract: Health)",
    responses={
        200: ok("Service status", "Health", "Healthy"),
        **error_responses(500),
    },
)
def health() -> dict:
    try:
        with psycopg.connect(database_url(), connect_timeout=2) as conn:
            rows = conn.execute(
                "SELECT extname FROM pg_extension WHERE extname = ANY(%s) ORDER BY extname",
                (sorted(REQUIRED_EXTENSIONS),),
            ).fetchall()
        db = {"reachable": True, "extensions": [r[0] for r in rows]}
    except psycopg.OperationalError:
        db = {"reachable": False, "extensions": []}

    healthy = db["reachable"] and set(db["extensions"]) >= REQUIRED_EXTENSIONS
    return {
        "status": "ok" if healthy else "degraded",
        "service": "echr-lookup-api",
        "version": VERSION,
        "db": db,
        "data_source": data_source(),
    }
