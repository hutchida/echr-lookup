"""OpenAPI helpers: the contract's JSON Schemas become the API's schemas, and the contract
fixtures become the examples shown on /docs, so the documentation cannot drift from the contract."""

import copy
import json
from functools import cache
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from rag.contract import FIXTURE_DIR, SCHEMA_DIR, load_fixture

_DEFS = "#/$defs/"
_COMPONENTS = "#/components/schemas/"

# Extra request examples for the demo questions (docs/orchestration/tasks/S5.md, demo path).
DEMO_QUESTIONS = {
    "deportation": "Does the Convention stop the UK deporting criminals?",
    "article_8": "How has Article 8 been applied in UK immigration cases?",
    "stats": (
        "How many UK deportation complaints in the corpus were declared inadmissible, "
        "and the most common reasons?"
    ),
}


def _rewrite_ref(value: str) -> str:
    return _COMPONENTS + value[len(_DEFS) :] if value.startswith(_DEFS) else value


def _rewrite(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: _rewrite_ref(v) if k == "$ref" else _rewrite(v)
            for k, v in node.items()
            if k != "$schema"
        }
    if isinstance(node, list):
        return [_rewrite(v) for v in node]
    return node


@cache
def contract_schemas() -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        for name, schema in json.loads(path.read_text()).get("$defs", {}).items():
            schemas.setdefault(name, _rewrite(schema))
    return schemas


def ref(name: str) -> dict:
    return {"$ref": f"{_COMPONENTS}{name}"}


def example(fixture: str, summary: str) -> dict:
    return {"summary": summary, "value": load_fixture(fixture)}


def fixture_exists(name: str) -> bool:
    return (FIXTURE_DIR / f"{name}.json").exists()


def json_content(schema: str, examples: dict[str, dict]) -> dict:
    return {"application/json": {"schema": ref(schema), "examples": examples}}


def response_doc(description: str, schema: str, examples: dict[str, dict] | None = None) -> dict:
    return {"description": description, "content": json_content(schema, examples or {})}


def ok(description: str, schema: str, summary: str) -> dict:
    """200 response documented with the contract fixture of the same name as its example."""
    return response_doc(description, schema, {"fixture": example(schema, summary)})


def error_responses(*statuses: int) -> dict[int | str, dict]:
    """ApiError documentation for the given statuses (404 gets the fixture as its example)."""
    docs = {
        404: ("Not found", {"not_found": example("ApiError", "Unknown case id")}),
        422: ("The request body or parameters break the contract", {}),
        500: ("Unexpected server error (a bug; quote the request_id)", {}),
        503: ("The database or a not-yet-available component is unavailable", {}),
    }
    return {s: response_doc(docs[s][0], "ApiError", docs[s][1]) for s in statuses}


def request_body(schema: str, examples: dict[str, dict]) -> dict:
    return {
        "requestBody": {"required": True, "content": json_content(schema, examples)},
    }


def _restore_examples(routes: list, spec: dict) -> None:
    """FastAPI drops every `null` while building the spec, which would make the contract's
    examples invalid (e.g. `rerank_score: null`). Copy the declared content back untouched."""
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            operation = spec["paths"][route.path_format][method.lower()]
            for status, declared in route.responses.items():
                if "content" in declared:
                    operation["responses"][str(status)]["content"] = copy.deepcopy(
                        declared["content"]
                    )
            if route.openapi_extra and "requestBody" in route.openapi_extra:
                operation["requestBody"] = copy.deepcopy(route.openapi_extra["requestBody"])


def install_openapi(app: FastAPI, *routers: APIRouter) -> None:
    routers_routes = [route for router in routers for route in router.routes]

    def build() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        spec = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        spec.setdefault("components", {}).setdefault("schemas", {}).update(contract_schemas())
        _restore_examples([*app.routes, *routers_routes], spec)
        app.openapi_schema = spec
        return spec

    app.openapi = build  # type: ignore[method-assign]
