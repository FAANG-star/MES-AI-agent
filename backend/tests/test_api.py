"""HTTP surface tests, driven through the real ASGI app (lifespan included)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def test_health_reports_the_factory_clock_and_a_read_only_connection(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"]["connected"] is True
    assert body["database"]["user"] == "mes_ro"
    assert body["database"]["read_only"] is True
    assert body["database"]["machines"] == 5
    assert body["factory"]["timezone"] == "Asia/Tokyo"
    assert body["tools"] == {"total": 8, "implemented": 7}


def test_machines_endpoint_feeds_the_status_strip(client):
    body = client.get("/api/machines").json()
    assert len(body["data"]["machines"]) == 5
    assert body["sources"]
    ids = [m["machine_id"] for m in body["data"]["machines"]]
    assert ids == ["CNC-01", "CNC-02", "CNC-03", "CNC-04", "CNC-05"]


def test_tool_catalogue_lists_exactly_the_eight_controlled_tools(client):
    body = client.get("/api/tools").json()
    assert len(body["tools"]) == 8
    assert len(body["implemented"]) == 7
    assert "this_week" in body["time_windows"]


def test_single_tool_contract_is_browsable(client):
    body = client.get("/api/tools/get_part_information").json()
    assert body["name"] == "get_part_information"
    assert "part_id" in body["input_schema"]["properties"]


def test_invoking_a_tool_over_http_returns_the_envelope(client):
    body = client.post("/api/tools/get_part_information", json={"part_id": "A12"}).json()
    assert body["data"]["part"]["cycle_time_min"] == 3.5
    assert body["ok"] is True
    assert body["sources"][0]["table"] == "parts"
    assert body["elapsed_ms"] is not None


def test_missing_data_is_visible_in_the_http_response(client):
    body = client.post("/api/tools/get_part_information", json={"part_id": "B20"}).json()
    assert body["data"]["part"]["cycle_time_min"] is None
    assert body["missing_fields"][0]["field"] == "parts.cycle_time_min"


def test_tool_with_no_body_uses_its_defaults(client):
    r = client.post("/api/tools/get_machine_status")
    assert r.status_code == 200
    assert len(r.json()["data"]["machines"]) == 5


def test_unknown_tool_is_404_and_lists_what_exists(client):
    r = client.post("/api/tools/run_raw_sql", json={})
    assert r.status_code == 404
    assert "get_machine_status" in r.json()["detail"]


def test_unbuilt_tool_is_501_and_says_when_it_arrives(client):
    r = client.post("/api/tools/calculate_production_capacity", json={"part_id": "A12"})
    assert r.status_code == 501
    assert r.json()["detail"]["planned_for"].startswith("Day 6")


def test_invalid_parameters_are_422_not_a_guess(client):
    r = client.post("/api/tools/get_part_information", json={})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "invalid_parameters"


def test_invalid_time_window_is_422_with_guidance(client):
    r = client.post("/api/tools/get_available_machines", json={"time_window": "next_quarter"})
    assert r.status_code == 422
    assert "this_week" in r.json()["detail"]["message"]


def test_openapi_documents_the_tool_surface(client):
    spec = client.get("/openapi.json").json()
    assert "/api/tools/{tool_name}" in spec["paths"]
    assert "/api/machines" in spec["paths"]


# --------------------------------------------------------- Day 4: understanding


def test_health_reports_the_agent_configuration(client):
    agent = client.get("/api/health").json()["agent"]
    assert agent["llm_provider"] in {"none", "anthropic", "openai_compatible"}
    assert agent["understanding"] in {"llm", "deterministic_rules"}


def test_agent_endpoint_describes_the_pipeline(client):
    body = client.get("/api/agent").json()
    assert body["pipeline"] == [
        "domain_guard",
        "rewrite_and_intent",
        "entity_resolution",
        "tool_selection",
    ]
    assert "production_capacity" in body["intents"]
    assert body["llm"]["model"]


def test_understand_returns_a_plan_for_the_hero_scenario(client):
    body = client.post(
        "/api/understand", json={"question": "How many A12 parts can we produce this week?"}
    ).json()
    assert body["status"] == "understood"
    assert body["intent"] == "production_capacity"
    assert [s["tool"] for s in body["plan"]][0] == "get_part_information"
    assert body["rewritten_question"]
    assert body["window"]["timezone"] == "Asia/Tokyo"


def test_understand_rejects_an_out_of_domain_request(client):
    body = client.post("/api/understand", json={"question": "Write me a story."}).json()
    assert body["status"] == "rejected_out_of_domain"
    assert body["rejection"].startswith("This AI assistant is restricted")
    assert body["plan"] == []


def test_understand_asks_for_clarification_when_ambiguous(client):
    body = client.post("/api/understand", json={"question": "How many A12?"}).json()
    assert body["status"] == "clarify"
    assert body["clarification"]["options"]


def test_understand_rejects_an_empty_question(client):
    assert client.post("/api/understand", json={"question": ""}).status_code == 422
    assert client.post("/api/understand", json={}).status_code == 422


def test_understand_reports_which_path_produced_the_reading(client):
    body = client.post("/api/understand", json={"question": "A12 capacity this week"}).json()
    assert body["understood_by"] in {"llm", "rules"}
    assert isinstance(body["degraded"], bool)
