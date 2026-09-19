"""Tests for the governed-filter and resolve-result models.

``QueryFilterCondition`` enforces the governed filter contract client-side:
every condition needs a selector (``column`` or ``dimension_hint``), the
operator must be one of the supported set, and ``value``/``values`` must match
the operator's arity. These tests pin each rule and the whitespace
normalisation the validator applies.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_resolve_result import (
    QueryFilterCondition,
    QueryFilterSpec,
    ResolvedPlan,
    ResolveResult,
)


def make_resolve_result_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "confidence": 0.94,
        "plan": ["resolve_column", "aggregate"],
        "latency_ms": 8.5,
        "decision_path": "governed",
        "schema_revision": "rev_1",
        "validated": True,
        "deterministic_scope": "full",
        "confidence_source": "calibrated",
        "intent_signature": "sum(revenue)",
    }
    payload.update(overrides)
    return payload


class TestQueryFilterCondition:
    def test_scalar_condition_normalises_whitespace(self) -> None:
        condition = QueryFilterCondition.model_validate(
            {"column": "  region ", "op": " eq ", "value": "EMEA"}
        )

        assert condition.column == "region"
        assert condition.op == "eq"
        assert condition.dimension_hint is None

    def test_dimension_hint_is_an_acceptable_selector(self) -> None:
        condition = QueryFilterCondition.model_validate(
            {"dimension_hint": "sales region", "op": "gt", "value": 10}
        )

        assert condition.column is None
        assert condition.dimension_hint == "sales region"

    def test_blank_selectors_are_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="requires column or dimension_hint"):
            QueryFilterCondition.model_validate({"column": "   ", "op": "eq", "value": 1})

    def test_blank_operator_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="op is required"):
            QueryFilterCondition.model_validate({"column": "region", "op": "  ", "value": 1})

    def test_unsupported_operator_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="Unsupported filter operator 'like'"):
            QueryFilterCondition.model_validate({"column": "region", "op": "like", "value": "E%"})

    def test_in_requires_non_empty_values_and_no_value(self) -> None:
        condition = QueryFilterCondition.model_validate(
            {"column": "region", "op": "in", "values": ["EMEA", "APAC"]}
        )
        assert condition.values == ["EMEA", "APAC"]

        with pytest.raises(PydanticValidationError, match="does not accept value"):
            QueryFilterCondition.model_validate(
                {"column": "region", "op": "in", "value": "EMEA", "values": ["EMEA"]}
            )
        with pytest.raises(PydanticValidationError, match="requires non-empty values"):
            QueryFilterCondition.model_validate({"column": "region", "op": "in", "values": []})

    @pytest.mark.parametrize("op", ["is_null", "is_not_null"])
    def test_null_checks_take_no_operands(self, op: str) -> None:
        condition = QueryFilterCondition.model_validate({"column": "region", "op": op})
        assert condition.value is None and condition.values is None

        with pytest.raises(PydanticValidationError, match="do not accept value or values"):
            QueryFilterCondition.model_validate({"column": "region", "op": op, "value": 1})
        with pytest.raises(PydanticValidationError, match="do not accept value or values"):
            QueryFilterCondition.model_validate({"column": "region", "op": op, "values": [1]})

    @pytest.mark.parametrize("op", ["eq", "gt", "gte", "lt", "lte"])
    def test_scalar_operators_require_exactly_a_value(self, op: str) -> None:
        condition = QueryFilterCondition.model_validate({"column": "amount", "op": op, "value": 5})
        assert condition.value == 5

        with pytest.raises(PydanticValidationError, match=f"op='{op}' does not accept values"):
            QueryFilterCondition.model_validate({"column": "amount", "op": op, "values": [5]})
        with pytest.raises(PydanticValidationError, match=f"op='{op}' requires value"):
            QueryFilterCondition.model_validate({"column": "amount", "op": op})


class TestFilterSpecAndPlan:
    def test_filter_spec_defaults_to_no_conditions(self) -> None:
        spec = QueryFilterSpec.model_validate({})

        assert spec.time_filter is None
        assert spec.conditions == []

    def test_filter_spec_validates_nested_conditions(self) -> None:
        with pytest.raises(PydanticValidationError) as exc_info:
            QueryFilterSpec.model_validate(
                {"time_filter": "last_30_days", "conditions": [{"op": "eq", "value": 1}]}
            )

        assert exc_info.value.errors()[0]["loc"][:2] == ("conditions", 0)

    def test_resolved_plan_parses_defaults_and_nested_filter(self) -> None:
        plan = ResolvedPlan.model_validate(
            {
                "source_name": "orders",
                "metric_column": "revenue",
                "aggregation": "sum",
                "schema_revision": "rev_1",
                "filter": {
                    "time_filter": "last_30_days",
                    "conditions": [{"column": "region", "op": "eq", "value": "EMEA"}],
                },
            }
        )

        assert plan.order == "desc"
        assert plan.limit is None
        assert plan.constraints == {}
        assert plan.filter is not None
        assert plan.filter.conditions[0].value == "EMEA"


class TestResolveResult:
    def test_minimal_payload_applies_the_documented_defaults(self) -> None:
        result = ResolveResult.model_validate(make_resolve_result_payload())

        assert result.resolved_plan is None
        assert result.explanation == []
        assert result.resolved_column == ""
        assert result.candidates == []
        assert result.source_scores == {}
        assert result.clarification_required is False
        assert result.source_set == []
        assert result.join_path == []
        assert result.planner_mode is None

    def test_full_payload_nests_plan_and_candidates(self) -> None:
        result = ResolveResult.model_validate(
            make_resolve_result_payload(
                resolved_plan={
                    "source_name": "orders",
                    "metric_column": "revenue",
                    "aggregation": "sum",
                    "schema_revision": "rev_1",
                },
                candidates=[
                    {
                        "source": "orders",
                        "column": "revenue",
                        "role": "measure",
                        "confidence": 0.94,
                    },
                    {
                        "source": "orders",
                        "column": "margin",
                        "role": "measure",
                        "confidence": 0.31,
                    },
                ],
                source_scores={"orders": 0.94},
                source_set=["orders", "customers"],
                join_path=[{"left_source": "orders", "right_source": "customers"}],
                planner_mode="exact_spec",
                clarification_required=True,
                rejection_reason=None,
            )
        )

        assert result.resolved_plan is not None
        assert result.resolved_plan.metric_column == "revenue"
        assert [candidate.column for candidate in result.candidates] == ["revenue", "margin"]
        assert result.candidates[0].score_components == {}
        assert result.source_set == ["orders", "customers"]
        assert result.clarification_required is True

    def test_intent_signature_is_required(self) -> None:
        payload = make_resolve_result_payload()
        del payload["intent_signature"]

        with pytest.raises(PydanticValidationError) as exc_info:
            ResolveResult.model_validate(payload)

        assert exc_info.value.errors()[0]["loc"] == ("intent_signature",)
