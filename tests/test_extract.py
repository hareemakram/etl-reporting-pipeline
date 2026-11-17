import httpx

from etl.extract import extract_api, file_checksum, list_pending_order_files

from .conftest import PRODUCTS


def _transport(fail_first: int = 0):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= fail_first:
            return httpx.Response(503, json={"detail": "busy"})
        if request.url.path.endswith("/products"):
            page = int(request.url.params["page"])
            size = int(request.url.params["page_size"])
            chunk = PRODUCTS[(page - 1) * size: page * size]
            nxt = page + 1 if page * size < len(PRODUCTS) else None
            return httpx.Response(200, json={"data": chunk, "next_page": nxt})
        return httpx.Response(200, json={"base": "USD", "rates": {"usd": 1, "eur": 0.92}})
    return httpx.MockTransport(handler), calls


def test_api_pagination_and_retry(settings):
    s = settings.__class__(**{**settings.__dict__, "api_max_retries": 3})
    transport, calls = _transport(fail_first=2)
    logs = []
    res = extract_api(s, lambda lvl, msg: logs.append((lvl, msg)),
                      client=httpx.Client(transport=transport, base_url="http://api"))
    assert res.source == "api"
    assert res.retries == 2
    assert len(res.products) == 2
    assert res.fx_rates == {"USD": 1.0, "EUR": 0.92}
    assert sum(1 for lvl, _ in logs if lvl == "warning") == 2


def test_api_falls_back_to_fixture(settings):
    res = extract_api(settings)
    assert res.source == "fixture"
    assert set(res.products["product_id"]) == {"P0001", "P0002"}


def test_pending_files_uses_checksums(raw_dir):
    f = raw_dir / "orders" / "orders_2024_01.csv"
    assert list_pending_order_files(raw_dir / "orders", {}) == [f]
    assert list_pending_order_files(raw_dir / "orders", {f.name: file_checksum(f)}) == []
    f.write_text(f.read_text() + "ORD-99,2024-01-10,C00001,P0001,1,92.31,0,EUR,completed,web\n")
    assert list_pending_order_files(raw_dir / "orders", {f.name: "stale"}) == [f]
