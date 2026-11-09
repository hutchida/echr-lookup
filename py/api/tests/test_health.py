import time

from fastapi.testclient import TestClient

from api.main import app
from rag.contract import contract_errors, load_fixture

client = TestClient(app)


def test_health_matches_contract_and_db_is_ready():
    started = time.perf_counter()
    res = client.get("/health")
    elapsed = time.perf_counter() - started

    assert res.status_code == 200
    body = res.json()
    assert contract_errors("Health", body) == []
    # Requires `docker compose up -d` (ParadeDB). Both extensions must be installed.
    assert body["db"]["reachable"], "Postgres not reachable — run `docker compose up -d`"
    assert set(body["db"]["extensions"]) == {"pg_search", "vector"}
    assert body["status"] == "ok"
    assert elapsed < 1.0, f"/health took {elapsed:.2f}s (budget 1s)"


def test_contract_fixture_is_valid_from_python_too():
    assert contract_errors("Health", load_fixture("Health")) == []


def test_contract_rejects_bad_payload():
    assert contract_errors("Health", {"status": "ok"}) != []
