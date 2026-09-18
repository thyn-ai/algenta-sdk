"""Tests for the simulation surface: request shapes and envelope parsing."""

from __future__ import annotations

import uuid

import pytest
from httpx import Response

from decision_engine import AlgentaClient

from .conftest import TEST_BASE_URL, make_decision_envelope_payload, request_json


def test_simulate_posts_the_scenario_and_parses_the_envelope(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/simulate").mock(
        return_value=Response(200, json=make_decision_envelope_payload())
    )
    scenario = {
        "variables": {"revenue": {"low": 80000, "high": 200000}},
        "objective": "maximize_net_value",
    }

    result = client.simulate(mode="auto", scenario=scenario)

    assert request_json(route) == {"mode": "auto", "scenario": scenario}
    assert result.run_id == uuid.UUID("3f2b3f2b-3f2b-4f2b-8f2b-3f2b3f2b3f2b")
    assert result.recommended_action == "ship_it"
    assert result.confidence == pytest.approx(0.91)
    assert result.metrics.expected_value == pytest.approx(12500.0)
    assert result.percentiles.p95 == pytest.approx(14500.0)
    assert result.metadata.mode == "auto"


def test_simulate_normalizes_a_shorthand_variables_payload(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/simulate").mock(
        return_value=Response(200, json=make_decision_envelope_payload())
    )

    client.simulate(variables={"revenue": {"low": 1, "high": 2}}, runs=500)

    assert request_json(route) == {
        "mode": "auto",
        "scenario": {
            "variables": {"revenue": {"low": 1, "high": 2}},
            "objective": "maximize_net_value",
        },
        "runs": 500,
    }


def test_score_wraps_the_request_payload(client: AlgentaClient, mock_router) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/score").mock(
        return_value=Response(200, json={"score": 0.83, "score_breakdown": {"a": 1.0}})
    )

    result = client.score({"scenario": {"variables": {}}}, scoring_weights={"a": 1.0})

    assert request_json(route) == {
        "request": {"scenario": {"variables": {}}},
        "scoring_weights": {"a": 1.0},
    }
    assert result == {"score": 0.83, "score_breakdown": {"a": 1.0}}


def test_batch_posts_normalized_items_and_returns_results(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/batch").mock(
        return_value=Response(200, json={"results": [{"run_id": "r1"}, {"run_id": "r2"}]})
    )

    results = client.batch([{"variables": {"revenue": {"low": 1, "high": 2}}}])

    assert request_json(route) == {
        "items": [
            {
                "mode": "auto",
                "scenario": {
                    "variables": {"revenue": {"low": 1, "high": 2}},
                    "objective": "maximize_net_value",
                },
                "runs": 10000,
            }
        ]
    }
    assert results == [{"run_id": "r1"}, {"run_id": "r2"}]


def test_compare_normalizes_labeled_scenarios(client: AlgentaClient, mock_router) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/compare").mock(
        return_value=Response(200, json={"winner": "base"})
    )

    result = client.compare(
        scenarios=[{"label": "base", "variables": {"revenue": {"low": 1, "high": 2}}}]
    )

    assert request_json(route) == {
        "scenarios": [
            {
                "name": "base",
                "request": {
                    "mode": "auto",
                    "scenario": {
                        "variables": {"revenue": {"low": 1, "high": 2}},
                        "objective": "maximize_net_value",
                    },
                    "runs": 10000,
                },
            }
        ]
    }
    assert result == {"winner": "base"}
