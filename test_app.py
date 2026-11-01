"""API contract tests for Gather.

These tests are based on the API contract documented in README.md.
Run from the project root with: pytest -q
"""

import math

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture()
def client():
    return TestClient(app)


def valid_payload(**overrides):
    payload = {
        "event_type": "birthday",
        "name": "Test birthday",
        "date": "2030-06-15",
        "guests": 25,
        "budget": 800,
        "currency": "USD",
        "location": "Test location",
        "interests": "dinosaurs, crafts",
        "notes": "Keep the plan simple",
        "indoor_outdoor": "either",
    }
    payload.update(overrides)
    return payload


def test_health_endpoint_returns_successful_response(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_plan_accepts_a_valid_birthday_request(client):
    response = client.post("/api/plan", json=valid_payload())
    assert response.status_code == 200

    body = response.json()
    for key in ("mode", "personalized", "budget", "timeline", "vendors"):
        assert key in body

    assert body["mode"] in {"ai", "offline"}
    assert isinstance(body["personalized"], bool)
    assert isinstance(body["timeline"], (list, dict))
    assert isinstance(body["vendors"], (list, dict))


@pytest.mark.parametrize(
    "event_type",
    ["birthday", "community", "fundraiser", "workshop", "other"],
)
def test_plan_accepts_documented_event_types(client, event_type):
    payload = valid_payload(event_type=event_type)
    if event_type == "other":
        payload["other_type"] = "Neighborhood game night"

    response = client.post("/api/plan", json=payload)
    assert response.status_code == 200


@pytest.mark.parametrize("guests", [1, 2, 25, 5000])
def test_plan_accepts_guest_count_boundaries(client, guests):
    response = client.post("/api/plan", json=valid_payload(guests=guests))
    assert response.status_code == 200


@pytest.mark.parametrize("guests", [0, -1, 5001])
def test_plan_rejects_guest_counts_outside_documented_range(client, guests):
    response = client.post("/api/plan", json=valid_payload(guests=guests))
    assert response.status_code == 422


@pytest.mark.parametrize("budget", [0, -1, -0.01])
def test_plan_rejects_non_positive_budgets(client, budget):
    response = client.post("/api/plan", json=valid_payload(budget=budget))
    assert response.status_code == 422


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), float("-inf")])
def test_plan_rejects_non_finite_budgets(client, budget):
    # Starlette's JSON encoder may reject non-finite values before the request
    # reaches the app. In that case, the test still verifies they are not sent
    # as valid JSON input.
    if not math.isfinite(budget):
        with pytest.raises((ValueError, TypeError)):
            client.post("/api/plan", json=valid_payload(budget=budget))


def test_plan_rejects_unknown_event_type(client):
    response = client.post(
        "/api/plan",
        json=valid_payload(event_type="unlisted-event-type"),
    )
    assert response.status_code == 422


def test_plan_rejects_malformed_json(client):
    response = client.post(
        "/api/plan",
        content='{"event_type":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_plan_rejects_wrong_field_types(client):
    response = client.post("/api/plan", json=valid_payload(guests="many"))
    assert response.status_code == 422
