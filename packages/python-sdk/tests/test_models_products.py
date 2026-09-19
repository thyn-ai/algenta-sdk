"""Round-trip tests for the product-surface result models.

``decision_engine.models_products`` holds the responses of the five product
endpoints (decision, agent run, optimize, retrieve, forecast). The tests pin
required fields, list/dict defaults, the ``str | dict`` agent result union and
that unknown fields round-trip.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_products import (
    ProductAgentRunResult,
    ProductAgentStepResult,
    ProductDecisionResult,
    ProductForecastPeriodResult,
    ProductForecastResult,
    ProductOptimizeResult,
    ProductRetrieveHitResult,
    ProductRetrieveResult,
)

from .conftest import (
    make_product_agent_run_payload,
    make_product_decision_payload,
    make_product_forecast_payload,
)


class TestProductDecision:
    def test_parses_the_full_decision(self) -> None:
        decision = ProductDecisionResult.model_validate(make_product_decision_payload())

        assert decision.action == "launch"
        assert decision.why == ["EV > 0", "P(loss) < 10%"]
        assert decision.probability_of_loss == pytest.approx(0.08)
        assert decision.scenarios_evaluated == 10_000

    def test_why_defaults_to_an_empty_list(self) -> None:
        payload = make_product_decision_payload()
        del payload["why"]

        assert ProductDecisionResult.model_validate(payload).why == []

    def test_requires_the_risk_figures(self) -> None:
        payload = make_product_decision_payload()
        del payload["downside_risk"]

        with pytest.raises(PydanticValidationError) as exc_info:
            ProductDecisionResult.model_validate(payload)

        assert exc_info.value.errors()[0]["loc"] == ("downside_risk",)


class TestProductAgentRun:
    def test_step_defaults_status_tool_and_result(self) -> None:
        step = ProductAgentStepResult.model_validate({"step": 1, "action": "plan"})

        assert step.status == "completed"
        assert step.tool is None
        assert step.result is None

    def test_run_parses_steps_and_tools(self) -> None:
        run = ProductAgentRunResult.model_validate(make_product_agent_run_payload())

        assert run.result == "Shipped the release notes."
        assert [step.step for step in run.steps] == [1, 2]
        assert run.steps[0].tool == "fs.read"
        assert run.steps[1].status == "completed"
        assert run.tools_used == ["fs.read"]

    def test_run_accepts_a_structured_result(self) -> None:
        run = ProductAgentRunResult.model_validate(
            make_product_agent_run_payload(result={"summary": "done", "files": 3})
        )

        assert run.result == {"summary": "done", "files": 3}

    def test_run_defaults_steps_and_tools(self) -> None:
        payload = make_product_agent_run_payload()
        del payload["steps"]
        del payload["tools_used"]

        run = ProductAgentRunResult.model_validate(payload)

        assert run.steps == []
        assert run.tools_used == []

    def test_run_rejects_a_numeric_result(self) -> None:
        with pytest.raises(PydanticValidationError):
            ProductAgentRunResult.model_validate(make_product_agent_run_payload(result=42))


class TestProductOptimize:
    def test_parses_optimal_values(self) -> None:
        result = ProductOptimizeResult.model_validate(
            {
                "optimization_id": "opt_1",
                "status": "converged",
                "optimal_values": {"price": 19.99, "discount": 0.1},
                "objective_value": 4_210.5,
                "improvement_vs_midpoint": 0.17,
                "constraints_satisfied": True,
                "iterations_run": 250,
                "latency_ms": 133.0,
            }
        )

        assert result.optimal_values == {"price": 19.99, "discount": 0.1}
        assert result.constraints_satisfied is True
        assert result.iterations_run == 250

    def test_optimal_values_default_to_an_empty_dict(self) -> None:
        result = ProductOptimizeResult.model_validate(
            {
                "optimization_id": "opt_1",
                "status": "infeasible",
                "objective_value": 0.0,
                "improvement_vs_midpoint": 0.0,
                "constraints_satisfied": False,
                "iterations_run": 1,
                "latency_ms": 2.0,
            }
        )

        assert result.optimal_values == {}


class TestProductRetrieve:
    def test_hit_defaults_document_id(self) -> None:
        hit = ProductRetrieveHitResult.model_validate(
            {"rank": 1, "content": "full text", "relevance_score": 0.77, "snippet": "full..."}
        )

        assert hit.document_id is None

    def test_result_nests_ranked_hits(self) -> None:
        result = ProductRetrieveResult.model_validate(
            {
                "retrieval_id": "ret_1",
                "query": "retry policy",
                "results": [
                    {
                        "rank": 1,
                        "document_id": "doc_9",
                        "content": "The retry loop ...",
                        "relevance_score": 0.93,
                        "snippet": "retry loop",
                    },
                    {
                        "rank": 2,
                        "content": "Back-off doubles ...",
                        "relevance_score": 0.71,
                        "snippet": "back-off",
                    },
                ],
                "total_searched": 1_204,
                "latency_ms": 18.0,
            }
        )

        assert [hit.rank for hit in result.results] == [1, 2]
        assert result.results[0].document_id == "doc_9"
        assert result.results[1].document_id is None
        assert result.total_searched == 1_204

    def test_result_defaults_hits_to_an_empty_list(self) -> None:
        result = ProductRetrieveResult.model_validate(
            {"retrieval_id": "ret_1", "query": "nothing", "total_searched": 0, "latency_ms": 1.0}
        )

        assert result.results == []


class TestProductForecast:
    def test_period_parses_bounds_and_trend(self) -> None:
        period = ProductForecastPeriodResult.model_validate(
            {
                "period": 3,
                "forecast": 120.0,
                "lower_bound": 100.0,
                "upper_bound": 140.0,
                "trend": "flat",
            }
        )

        assert period.trend == "flat"
        assert period.lower_bound < period.forecast < period.upper_bound

    def test_forecast_nests_ordered_periods(self) -> None:
        forecast = ProductForecastResult.model_validate(make_product_forecast_payload())

        assert forecast.metric == "revenue"
        assert [period.period for period in forecast.periods] == [1, 2]
        assert forecast.total_change_pct == pytest.approx(12.0)
        assert forecast.periods[1].forecast == pytest.approx(forecast.forecast_mean)

    def test_forecast_defaults_periods_to_an_empty_list(self) -> None:
        payload = make_product_forecast_payload()
        del payload["periods"]

        assert ProductForecastResult.model_validate(payload).periods == []


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ProductDecisionResult, make_product_decision_payload()),
        (ProductAgentRunResult, make_product_agent_run_payload()),
        (ProductForecastResult, make_product_forecast_payload()),
    ],
)
def test_unknown_server_fields_survive_a_round_trip(model: type, payload: dict[str, Any]) -> None:
    enriched = {**payload, "future_field": [1, 2]}

    parsed = model.model_validate(enriched)
    dumped = parsed.model_dump(mode="json")

    assert dumped["future_field"] == [1, 2]
    assert model.model_validate(dumped) == parsed
