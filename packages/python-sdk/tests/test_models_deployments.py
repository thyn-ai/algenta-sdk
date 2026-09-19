"""Round-trip tests for the deployment result models.

``DeploymentRegionResult`` carries a pre-validator that mirrors ``name`` and
``label`` onto each other when the server sends only one of them; the other
classes are plain permissive models whose required fields and defaults are
pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine.models_deployments import (
    DeploymentCostResult,
    DeploymentDeleteResult,
    DeploymentProviderResult,
    DeploymentRegionResult,
    DeploymentRegionsResult,
    DeploymentResult,
)

from .conftest import (
    make_deployment_payload,
)

_TS = "2026-01-01T00:00:00Z"
_TS_DT = datetime(2026, 1, 1, tzinfo=UTC)


class TestDeploymentRegionAliases:
    def test_name_and_label_are_both_kept_when_both_are_sent(self) -> None:
        region = DeploymentRegionResult.model_validate(
            {"id": "eu-west-1", "name": "eu-west-1", "label": "Ireland", "location": "Dublin"}
        )

        assert region.name == "eu-west-1"
        assert region.label == "Ireland"
        assert region.location == "Dublin"

    def test_a_missing_name_is_filled_from_the_label(self) -> None:
        region = DeploymentRegionResult.model_validate({"id": "eu-west-1", "label": "Ireland"})

        assert region.name == "Ireland"
        assert region.label == "Ireland"

    def test_a_missing_label_is_filled_from_the_name(self) -> None:
        region = DeploymentRegionResult.model_validate({"id": "eu-west-1", "name": "eu-west-1"})

        assert region.label == "eu-west-1"
        assert region.location is None

    def test_an_empty_name_counts_as_missing(self) -> None:
        region = DeploymentRegionResult.model_validate(
            {"id": "eu-west-1", "name": "", "label": "Ireland"}
        )

        assert region.name == "Ireland"

    def test_neither_name_nor_label_fails_validation(self) -> None:
        with pytest.raises(PydanticValidationError) as exc_info:
            DeploymentRegionResult.model_validate({"id": "eu-west-1"})

        assert exc_info.value.errors()[0]["loc"] == ("name",)

    def test_non_dict_input_is_passed_through_to_pydantic(self) -> None:
        """The alias normaliser only rewrites mappings; anything else fails normally."""
        with pytest.raises(PydanticValidationError):
            DeploymentRegionResult.model_validate(["eu-west-1"])

    def test_the_input_mapping_is_not_mutated(self) -> None:
        payload = {"id": "eu-west-1", "label": "Ireland"}

        DeploymentRegionResult.model_validate(payload)

        assert payload == {"id": "eu-west-1", "label": "Ireland"}


class TestProviderCatalog:
    def test_provider_nests_regions(self) -> None:
        provider = DeploymentProviderResult.model_validate(
            {
                "id": "aws",
                "name": "Amazon Web Services",
                "description": "Dedicated engine in your AWS account.",
                "icon": "aws",
                "regions": [{"id": "eu-west-1", "label": "Ireland"}],
            }
        )

        assert provider.regions[0].name == "Ireland"

    def test_provider_defaults_regions_to_an_empty_list(self) -> None:
        provider = DeploymentProviderResult.model_validate(
            {"id": "gcp", "name": "Google Cloud", "description": "GCP", "icon": "gcp"}
        )

        assert provider.regions == []

    def test_regions_result_defaults_providers(self) -> None:
        assert DeploymentRegionsResult.model_validate({}).providers == []

    def test_regions_result_nests_providers(self) -> None:
        result = DeploymentRegionsResult.model_validate(
            {
                "providers": [
                    {
                        "id": "aws",
                        "name": "AWS",
                        "description": "AWS",
                        "icon": "aws",
                        "regions": [{"id": "us-east-1", "name": "us-east-1"}],
                    }
                ]
            }
        )

        assert result.providers[0].regions[0].label == "us-east-1"


class TestDeploymentLifecycle:
    def test_deployment_parses_the_provisioning_state(self) -> None:
        deployment = DeploymentResult.model_validate(make_deployment_payload())

        assert deployment.status == "provisioning"
        assert deployment.endpoint_url is None
        assert deployment.provisioned_at is None
        assert deployment.error_message is None
        assert deployment.created_at == _TS_DT

    def test_deployment_parses_the_ready_state(self) -> None:
        deployment = DeploymentResult.model_validate(
            make_deployment_payload(
                status="ready",
                endpoint_url="https://engine.example.com",
                provisioned_at=_TS,
            )
        )

        assert deployment.endpoint_url == "https://engine.example.com"
        assert deployment.provisioned_at == _TS_DT

    def test_deployment_requires_billing_figures(self) -> None:
        payload = make_deployment_payload()
        del payload["billable_cost_usd_month"]

        with pytest.raises(PydanticValidationError) as exc_info:
            DeploymentResult.model_validate(payload)

        assert exc_info.value.errors()[0]["loc"] == ("billable_cost_usd_month",)

    def test_delete_result_parses(self) -> None:
        result = DeploymentDeleteResult.model_validate(
            {"status": "deleted", "deployment_id": "dep_1"}
        )

        assert result.status == "deleted"
        assert result.deployment_id == "dep_1"

    def test_cost_result_parses_and_defaults_last_updated(self) -> None:
        cost = DeploymentCostResult.model_validate(
            {
                "deployment_id": "dep_1",
                "provider": "aws",
                "region": "eu-west-1",
                "year": 2026,
                "month": 9,
                "cost_usd_month": 420.0,
                "billable_cost_usd_month": 504.0,
                "billing_markup_pct": 20.0,
            }
        )

        assert (cost.year, cost.month) == (2026, 9)
        assert cost.last_updated is None

    def test_cost_result_parses_last_updated(self) -> None:
        cost = DeploymentCostResult.model_validate(
            {
                "deployment_id": "dep_1",
                "provider": "aws",
                "region": "eu-west-1",
                "year": 2026,
                "month": 9,
                "cost_usd_month": 420.0,
                "billable_cost_usd_month": 504.0,
                "billing_markup_pct": 20.0,
                "last_updated": _TS,
            }
        )

        assert cost.last_updated == _TS_DT


def test_unknown_server_fields_survive_a_round_trip() -> None:
    parsed = DeploymentResult.model_validate(make_deployment_payload(future_field="kept"))
    dumped = parsed.model_dump(mode="json")

    assert dumped["future_field"] == "kept"
    assert DeploymentResult.model_validate(dumped) == parsed
