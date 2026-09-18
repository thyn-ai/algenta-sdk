"""Tests for the retry transport and the back-off policy helpers."""

from __future__ import annotations

import httpx
import pytest
from httpx import Response

from decision_engine import AlgentaClient
from decision_engine.exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from decision_engine.transport_retry_policy import (
    DEFAULT_RETRY_AFTER_SECONDS,
    INLINE_PREVIEW_RATE_LIMIT_ERROR,
    parse_retry_after_header,
    rate_limit_backoff_seconds,
    server_error_backoff_seconds,
    should_retry_rate_limit,
)

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response

_DATASET_PAGE = {"datasets": [], "count": 0, "total": 0, "page": 1, "limit": 200, "pages": 0}


def _client(max_retries: int = 3) -> AlgentaClient:
    return AlgentaClient(
        api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=max_retries
    )


def test_server_error_is_retried_until_success(mock_router, recorded_sleeps) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=[
            error_response(500, message="boom"),
            error_response(502, message="boom again"),
            Response(200, json=_DATASET_PAGE),
        ]
    )

    result = _client().list_datasets()

    assert result.total == 0
    assert route.call_count == 3
    # Server-error back-off: 2**attempt * 1s.
    assert recorded_sleeps == [1.0, 2.0]


def test_server_error_raises_after_exhausting_retries(mock_router, recorded_sleeps) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=[error_response(500), error_response(500), error_response(500)]
    )

    with pytest.raises(ServerError):
        _client(max_retries=2).list_datasets()

    assert route.call_count == 3
    assert recorded_sleeps == [1.0, 2.0]


def test_rate_limit_honors_the_retry_after_header(mock_router, recorded_sleeps) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=[
            error_response(429, headers={"Retry-After": "7"}),
            Response(200, json=_DATASET_PAGE),
        ]
    )

    result = _client().list_datasets()

    assert result.total == 0
    assert route.call_count == 2
    assert recorded_sleeps == [7.0]


def test_rate_limit_without_a_header_backs_off_by_the_default(
    mock_router, recorded_sleeps
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=[
            error_response(429),
            Response(200, json=_DATASET_PAGE),
        ]
    )

    _client().list_datasets()

    assert recorded_sleeps == [float(DEFAULT_RETRY_AFTER_SECONDS)]


def test_rate_limit_raises_after_exhausting_retries(mock_router, recorded_sleeps) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=[error_response(429, headers={"Retry-After": "3"})] * 3
    )

    with pytest.raises(RateLimitError) as exc_info:
        _client(max_retries=2).list_datasets()

    assert exc_info.value.retry_after == 3
    assert route.call_count == 3
    assert recorded_sleeps == [3.0, 3.0]


def test_inline_preview_rate_limit_is_never_retried(mock_router, recorded_sleeps) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=error_response(429, code=INLINE_PREVIEW_RATE_LIMIT_ERROR)
    )

    with pytest.raises(RateLimitError):
        _client().list_datasets()

    assert route.call_count == 1
    assert recorded_sleeps == []


@pytest.mark.parametrize(
    ("status", "exception_type"),
    [(401, AuthenticationError), (404, NotFoundError), (422, ValidationError)],
)
def test_client_errors_are_never_retried(
    mock_router, recorded_sleeps, status: int, exception_type: type[Exception]
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        return_value=error_response(status)
    )

    with pytest.raises(exception_type):
        _client().list_datasets()

    assert route.call_count == 1
    assert recorded_sleeps == []


def test_transport_errors_are_retried_with_server_backoff(
    mock_router, recorded_sleeps
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            Response(200, json=_DATASET_PAGE),
        ]
    )

    result = _client().list_datasets()

    assert result.total == 0
    assert route.call_count == 2
    assert recorded_sleeps == [1.0]


def test_transport_error_raises_after_exhausting_retries(
    mock_router, recorded_sleeps
) -> None:
    mock_router.get(f"{TEST_BASE_URL}/v1/data").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with pytest.raises(httpx.ConnectError):
        _client(max_retries=1).list_datasets()

    assert recorded_sleeps == [1.0]


# --- Back-off policy unit tests -------------------------------------------


def test_parse_retry_after_header_handles_missing_and_blank_values() -> None:
    assert parse_retry_after_header(None) == DEFAULT_RETRY_AFTER_SECONDS
    assert parse_retry_after_header("") == DEFAULT_RETRY_AFTER_SECONDS
    assert parse_retry_after_header("   ") == DEFAULT_RETRY_AFTER_SECONDS


def test_parse_retry_after_header_parses_integer_seconds() -> None:
    assert parse_retry_after_header("5") == 5
    assert parse_retry_after_header(" 12 ") == 12


def test_parse_retry_after_header_clamps_negative_values_to_zero() -> None:
    assert parse_retry_after_header("-3") == 0


def test_parse_retry_after_header_falls_back_on_garbage() -> None:
    assert parse_retry_after_header("not-a-date") == DEFAULT_RETRY_AFTER_SECONDS


def test_parse_retry_after_header_parses_http_dates() -> None:
    far_future = parse_retry_after_header("Wed, 21 Oct 2099 07:28:00 GMT")
    assert far_future > 0
    past = parse_retry_after_header("Thu, 01 Jan 1970 00:00:00 GMT")
    assert past == 0


def test_server_error_backoff_doubles_per_attempt() -> None:
    assert server_error_backoff_seconds(attempt=0) == 1.0
    assert server_error_backoff_seconds(attempt=1) == 2.0
    assert server_error_backoff_seconds(attempt=3) == 8.0


def test_rate_limit_backoff_prefers_an_explicit_retry_after() -> None:
    assert rate_limit_backoff_seconds(3, attempt=0) == 3.0
    assert rate_limit_backoff_seconds(None, attempt=0) == 5.0
    assert rate_limit_backoff_seconds(None, attempt=2) == 20.0
    assert rate_limit_backoff_seconds(0, attempt=1) == 10.0


def test_should_retry_rate_limit_only_exempts_inline_preview() -> None:
    assert should_retry_rate_limit(None) is True
    assert should_retry_rate_limit("quota_exceeded") is True
    assert should_retry_rate_limit(INLINE_PREVIEW_RATE_LIMIT_ERROR) is False
