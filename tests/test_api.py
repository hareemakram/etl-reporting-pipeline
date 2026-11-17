"""API smoke tests over a database loaded by the real pipeline."""
import pytest
from fastapi.testclient import TestClient

from etl.pipeline import run_pipeline

from .conftest import TODAY


@pytest.fixture
def client(engine, settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("RAW_DATA_DIR", str(settings.raw_dir))
    monkeypatch.setenv("FIXTURES_DIR", str(settings.fixtures_dir))
    monkeypatch.setenv("MOCK_API_FAILURE_RATE", "0")
    run_pipeline(engine, settings, today=TODAY)
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_reporting_endpoints(client):
    ov = client.get("/api/overview").json()["current"]
    assert ov["orders"] == 3 and ov["revenue"] == pytest.approx(180 + 50 + 3000)
    monthly = client.get("/api/sales/monthly").json()
    assert monthly == [{"month": "2024-01", "revenue": pytest.approx(3230.0), "orders": 3, "aov": pytest.approx(1076.67)}]
    assert {r["region"] for r in client.get("/api/sales/by-region").json()} == {"Europe", "North America"}
    assert client.get("/api/sales/top-products?limit=1").json()[0]["product_id"] == "P0002"
    eu = client.get("/api/overview", params={"region": "Europe"}).json()["current"]
    assert eu["orders"] == 1


def test_pipeline_and_quality_endpoints(client):
    runs = client.get("/api/runs").json()
    assert len(runs) == 1 and runs[0]["status"] == "success"
    detail = client.get(f"/api/runs/{runs[0]['run_id']}").json()
    assert any(r["rule_name"] == "email_valid" and r["rows_failed"] == 1 for r in detail["rules"])
    issues = client.get("/api/quality/issues", params={"rule": "currency_supported"}).json()
    assert issues["total"] == 1 and issues["items"][0]["columns"] == ["currency"]
    csv = client.get("/api/quality/issues.csv", params={"severity": "error"}).text
    assert csv.splitlines()[0].startswith("run_id,dataset,source_file") and len(csv.splitlines()) == 11
    assert client.get("/api/pipeline/status").json()["pending_files"] == []
    assert client.get("/api/runs/999").status_code == 404


def test_mock_api_paginates(client):
    body = client.get("/mock-api/products", params={"page": 1, "page_size": 1}).json()
    assert body["next_page"] == 2 and len(body["data"]) == 1


def test_ui_served(client):
    assert "Reporting ETL" in client.get("/").text
