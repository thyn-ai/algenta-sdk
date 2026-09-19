"""Tests for the signed runtime-admin surface: modules, benchmarks, release validation.

These three admin endpoints share ``get_runtime_manifest``'s contract: a
strict, signed payload with no OpenAPI fallback. A body that fails model
validation is reported as ``invalid_runtime_contract_payload`` with the
pydantic error locations attached; transport errors propagate as their typed
exceptions. The async facade is exercised for each, along with the async
``get_contract`` invalid-payload path, which is the public-contract twin.
"""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import AuthenticationError, DecisionEngineError, NotFoundError
from decision_engine.models_runtime_manifest import (
    RuntimeAdminBenchmarksResult,
    RuntimeAdminModulesResult,
    RuntimeReleaseValidationResult,
)

from .conftest import (
    TEST_API_KEY,
    TEST_BASE_URL,
    error_response,
    make_runtime_admin_benchmarks_payload,
    make_runtime_admin_modules_payload,
    make_runtime_release_validation_payload,
)

_MODULES = f"{TEST_BASE_URL}/v1/admin/runtime/modules"
_BENCHMARKS = f"{TEST_BASE_URL}/v1/admin/runtime/benchmarks"
_VALIDATION = f"{TEST_BASE_URL}/v1/admin/runtime/validation"


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestSync:
    def test_get_runtime_modules_parses_the_signed_inventory(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_MODULES).mock(
            return_value=Response(200, json=make_runtime_admin_modules_payload())
        )

        result = client.get_runtime_modules()

        assert route.calls[0].request.method == "GET"
        assert isinstance(result, RuntimeAdminModulesResult)
        assert [module.name.value for module in result.modules] == ["bpe_tokenizer", "embeddings"]
        assert result.summary.function_count == 5

    def test_get_runtime_benchmarks_parses_the_signed_ledger(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_BENCHMARKS).mock(
            return_value=Response(200, json=make_runtime_admin_benchmarks_payload())
        )

        result = client.get_runtime_benchmarks()

        assert isinstance(result, RuntimeAdminBenchmarksResult)
        assert result.evaluation_summary.rag_quality_gate_enabled is True
        assert result.module_benchmarks[1].benchmark_speedup_x == pytest.approx(6.5)

    def test_get_runtime_release_validation_parses_the_theorem(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_VALIDATION).mock(
            return_value=Response(200, json=make_runtime_release_validation_payload())
        )

        result = client.get_runtime_release_validation()

        assert isinstance(result, RuntimeReleaseValidationResult)
        assert result.valid_release is True
        assert [condition.condition.value for condition in result.conditions] == [
            "manifest-listed",
            "proof-backed",
        ]

    @pytest.mark.parametrize(
        ("url", "method_name"),
        [
            (_MODULES, "get_runtime_modules"),
            (_BENCHMARKS, "get_runtime_benchmarks"),
            (_VALIDATION, "get_runtime_release_validation"),
        ],
    )
    def test_an_invalid_body_is_reported_as_an_invalid_signed_payload(
        self, client: AlgentaClient, mock_router, url: str, method_name: str
    ) -> None:
        mock_router.get(url).mock(return_value=Response(200, json={"runtime_version": "1.0.0"}))

        with pytest.raises(DecisionEngineError) as exc_info:
            getattr(client, method_name)()

        error = exc_info.value
        assert error.error_code == "invalid_runtime_contract_payload"
        assert str(error) == f"{method_name}() returned an invalid signed payload."
        assert error.details is not None
        paths = {item["path"] for item in error.details["validation_errors"]}
        assert "manifest_digest" in paths
        assert "signature" in paths

    def test_an_inconsistent_body_reports_the_integrity_rule(
        self, client: AlgentaClient, mock_router
    ) -> None:
        payload = make_runtime_admin_modules_payload()
        payload["summary"]["module_count"] = 9
        mock_router.get(_MODULES).mock(return_value=Response(200, json=payload))

        with pytest.raises(DecisionEngineError) as exc_info:
            client.get_runtime_modules()

        # Model-level validator failures carry no pydantic location, so the SDK
        # recovers the field path from the message itself.
        errors = exc_info.value.details["validation_errors"]
        assert [error["path"] for error in errors] == ["summary.module_count"]
        assert "must equal the number of manifest modules" in errors[0]["message"]

    def test_there_is_no_fallback_on_not_found(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_BENCHMARKS).mock(
            return_value=error_response(404, message="admin surface disabled")
        )

        with pytest.raises(NotFoundError, match="admin surface disabled"):
            no_retry_client.get_runtime_benchmarks()

    def test_auth_errors_propagate_untouched(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_VALIDATION).mock(return_value=error_response(401, message="admin only"))

        with pytest.raises(AuthenticationError, match="admin only"):
            no_retry_client.get_runtime_release_validation()


class TestAsync:
    @pytest.mark.asyncio
    async def test_every_admin_endpoint_parses(self, mock_router) -> None:
        mock_router.get(_MODULES).mock(
            return_value=Response(200, json=make_runtime_admin_modules_payload())
        )
        mock_router.get(_BENCHMARKS).mock(
            return_value=Response(200, json=make_runtime_admin_benchmarks_payload())
        )
        mock_router.get(_VALIDATION).mock(
            return_value=Response(200, json=make_runtime_release_validation_payload())
        )

        async with _async_client() as client:
            modules = await client.get_runtime_modules()
            benchmarks = await client.get_runtime_benchmarks()
            validation = await client.get_runtime_release_validation()

        assert modules.shipping_contract.module_count == 2
        assert benchmarks.benchmark_discovery_lane.shipping_manifest_functions == 5
        assert validation.deployment_mode_raw == "saas"

    @pytest.mark.asyncio
    async def test_an_invalid_body_is_reported_as_an_invalid_signed_payload(
        self, mock_router
    ) -> None:
        mock_router.get(_MODULES).mock(return_value=Response(200, json={"modules": "nope"}))

        async with _async_client() as client:
            with pytest.raises(DecisionEngineError) as exc_info:
                await client.get_runtime_modules()

        assert exc_info.value.error_code == "invalid_runtime_contract_payload"
        assert "get_runtime_modules() returned an invalid signed payload." == str(exc_info.value)

    @pytest.mark.asyncio
    async def test_an_invalid_public_contract_is_reported_with_its_own_code(
        self, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/meta/contract").mock(
            return_value=Response(200, json={"contract_version": "v1.5"})
        )

        async with _async_client() as client:
            with pytest.raises(DecisionEngineError) as exc_info:
                await client.get_contract()

        assert exc_info.value.error_code == "invalid_contract_payload"
        assert str(exc_info.value) == "get_contract() returned an invalid payload."

    @pytest.mark.asyncio
    async def test_not_found_propagates_without_a_fallback(self, mock_router) -> None:
        mock_router.get(_VALIDATION).mock(return_value=error_response(404, message="not here"))

        async with _async_client() as client:
            with pytest.raises(NotFoundError, match="not here"):
                await client.get_runtime_release_validation()
