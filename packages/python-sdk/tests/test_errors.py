"""Tests for the HTTP status -> exception taxonomy and error payload parsing."""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AlgentaClient
from decision_engine.exceptions import (
    AuthenticationError,
    DecisionEngineError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

from .conftest import TEST_BASE_URL, error_response


def _mock_data(router, response: Response):
    return router.get(f"{TEST_BASE_URL}/v1/data").mock(return_value=response)


def test_400_raises_the_base_error_with_the_status_code(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, error_response(400, message="bad request"))

    with pytest.raises(DecisionEngineError) as exc_info:
        no_retry_client.list_datasets()

    assert type(exc_info.value) is DecisionEngineError
    assert exc_info.value.status_code == 400


def test_401_raises_authentication_error_with_the_server_message(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, error_response(401, message="invalid api key", code="invalid_key"))

    with pytest.raises(AuthenticationError) as exc_info:
        no_retry_client.list_datasets()

    assert str(exc_info.value) == "invalid api key"
    assert exc_info.value.status_code == 401
    assert exc_info.value.error_code == "invalid_key"


def test_401_without_a_message_falls_back_to_the_auth_default(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, Response(401, json={}))

    with pytest.raises(AuthenticationError, match="Authentication failed"):
        no_retry_client.list_datasets()


def test_404_raises_not_found(no_retry_client: AlgentaClient, mock_router) -> None:
    _mock_data(mock_router, error_response(404, message="dataset missing"))

    with pytest.raises(NotFoundError) as exc_info:
        no_retry_client.list_datasets()

    assert str(exc_info.value) == "dataset missing"
    assert exc_info.value.status_code == 404


def test_422_raises_validation_error_with_field_errors(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    field_errors = [{"field": "limit", "message": "must be positive"}]
    _mock_data(
        mock_router,
        error_response(422, message="validation error", details=field_errors),
    )

    with pytest.raises(ValidationError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.status_code == 422
    assert exc_info.value.details == field_errors
    assert exc_info.value.validation_errors == field_errors
    assert exc_info.value.field_errors == field_errors


def test_validation_errors_reads_the_nested_validation_errors_key(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    nested = [{"loc": ["body", "limit"], "msg": "required"}]
    _mock_data(
        mock_router,
        error_response(422, details={"validation_errors": nested}),
    )

    with pytest.raises(ValidationError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.validation_errors == nested


def test_validation_errors_is_empty_for_non_list_details(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, error_response(422, details={"other": "shape"}))

    with pytest.raises(ValidationError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.validation_errors == []
    assert exc_info.value.field_errors == []


def test_429_raises_rate_limit_error_with_retry_after(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(
        mock_router,
        error_response(429, message="slow down", headers={"Retry-After": "17"}),
    )

    with pytest.raises(RateLimitError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == 17


def test_429_without_a_retry_after_header_uses_the_default(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, error_response(429))

    with pytest.raises(RateLimitError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.retry_after == 60


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_raises_server_error(
    no_retry_client: AlgentaClient, mock_router, status: int
) -> None:
    _mock_data(mock_router, error_response(status, message="boom"))

    with pytest.raises(ServerError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.status_code == status


def test_non_json_error_body_yields_a_generic_message_and_empty_body(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, Response(500, text="Internal Server Error"))

    with pytest.raises(ServerError) as exc_info:
        no_retry_client.list_datasets()

    assert str(exc_info.value) == "Server error"
    assert exc_info.value.response_body == {}
    assert exc_info.value.error_code == "unknown_error"
    assert exc_info.value.request_id is None


def test_error_code_defaults_to_unknown_error(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, error_response(404, message="gone"))

    with pytest.raises(NotFoundError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.error_code == "unknown_error"


def test_body_request_id_wins_over_the_header(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(
        mock_router,
        error_response(
            404,
            request_id="req_from_body",
            headers={"X-Request-Id": "req_from_header"},
        ),
    )

    with pytest.raises(NotFoundError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.request_id == "req_from_body"


def test_request_id_is_none_when_neither_body_nor_header_carry_one(
    no_retry_client: AlgentaClient, mock_router
) -> None:
    _mock_data(mock_router, error_response(404))

    with pytest.raises(NotFoundError) as exc_info:
        no_retry_client.list_datasets()

    assert exc_info.value.request_id is None


def test_exception_repr_includes_the_structured_context() -> None:
    error = DecisionEngineError(
        "boom",
        status_code=500,
        response_body={"error": {"code": "kaput"}},
        request_id="req_1",
    )
    rendered = repr(error)
    assert "DecisionEngineError" in rendered
    assert "status_code=500" in rendered
    assert "'kaput'" in rendered
    assert "req_1" in rendered
