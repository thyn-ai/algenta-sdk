"""Tests for the Server-Sent Events helpers behind every streaming method.

``_iter_sse_payloads`` (sync and async) turns the raw line stream into JSON
payloads: ``data:`` lines buffer until a blank line, comments are skipped,
multi-line data joins with newlines, ``[DONE]`` ends the stream, and invalid
JSON raises the SDK's typed error with the offending payload attached.
``_stream_model`` wraps that parser around an HTTP stream and, like every other
request, persists a device-binding token the server hands back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient, device_binding
from decision_engine.async_client_stream_surface_common import (
    _iter_sse_payloads as _iter_sse_payloads_async,
)
from decision_engine.client_stream_surface_common import _iter_sse_payloads
from decision_engine.device_binding import DEVICE_BINDING_TOKEN_HEADER
from decision_engine.exceptions import DecisionEngineError

from .conftest import TEST_API_KEY, TEST_BASE_URL, derived_test_device_id

_SSE_HEADERS = {"content-type": "text/event-stream"}


async def _as_async(lines: Iterable[str]) -> AsyncIterator[str]:
    for line in lines:
        yield line


async def _collect(lines: Iterable[str]) -> list[object]:
    return [payload async for payload in _iter_sse_payloads_async(_as_async(lines))]


class TestSyncParser:
    def test_each_blank_line_flushes_one_payload(self) -> None:
        lines = ['data: {"n": 1}\n', "\n", 'data: {"n": 2}\r\n', "\r\n"]

        assert list(_iter_sse_payloads(lines)) == [{"n": 1}, {"n": 2}]

    def test_comment_and_non_data_lines_are_ignored(self) -> None:
        lines = [": keep-alive", "event: message", "id: 7", 'data: {"n": 1}', ""]

        assert list(_iter_sse_payloads(lines)) == [{"n": 1}]

    def test_consecutive_data_lines_join_with_newlines(self) -> None:
        lines = ['data: {"text":', 'data:  "two lines"}', ""]

        assert list(_iter_sse_payloads(lines)) == [{"text": "two lines"}]

    def test_leading_blank_lines_without_data_are_skipped(self) -> None:
        lines = ["", "", 'data: {"n": 1}', ""]

        assert list(_iter_sse_payloads(lines)) == [{"n": 1}]

    def test_done_marker_ends_the_stream_early(self) -> None:
        lines = ['data: {"n": 1}', "", "data: [DONE]", "", 'data: {"n": 2}', ""]

        assert list(_iter_sse_payloads(lines)) == [{"n": 1}]

    def test_a_trailing_payload_without_a_blank_line_is_flushed(self) -> None:
        assert list(_iter_sse_payloads(['data: {"n": 1}', "", 'data: {"n": 2}'])) == [
            {"n": 1},
            {"n": 2},
        ]

    def test_a_trailing_done_marker_is_swallowed(self) -> None:
        assert list(_iter_sse_payloads(['data: {"n": 1}', "", "data: [DONE]"])) == [{"n": 1}]

    def test_invalid_json_raises_the_typed_error_with_the_payload(self) -> None:
        with pytest.raises(DecisionEngineError) as exc_info:
            list(_iter_sse_payloads(["data: {not json", ""]))

        assert exc_info.value.error_code == "invalid_sse_event"
        assert exc_info.value.details == {"payload": "{not json"}
        assert "invalid JSON" in str(exc_info.value)

    def test_invalid_trailing_json_raises_the_trailing_variant(self) -> None:
        with pytest.raises(DecisionEngineError) as exc_info:
            list(_iter_sse_payloads(['data: {"n": 1}', "", "data: {oops"]))

        assert exc_info.value.error_code == "invalid_sse_event"
        assert "trailing" in str(exc_info.value)
        assert exc_info.value.details == {"payload": "{oops"}


class TestAsyncParser:
    @pytest.mark.asyncio
    async def test_matches_the_sync_parser_on_a_full_stream(self) -> None:
        lines = [
            ": hello",
            'data: {"n": 1}',
            "",
            "",
            'data: {"a":',
            'data: "b"}',
            "",
            "data: [DONE]",
            "",
            'data: {"n": 3}',
            "",
        ]

        assert await _collect(lines) == list(_iter_sse_payloads(lines)) == [{"n": 1}, {"a": "b"}]

    @pytest.mark.asyncio
    async def test_flushes_a_trailing_payload_and_swallows_a_trailing_done(self) -> None:
        assert await _collect(['data: {"n": 1}']) == [{"n": 1}]
        assert await _collect(['data: {"n": 1}', "", "data: [DONE]"]) == [{"n": 1}]

    @pytest.mark.asyncio
    async def test_invalid_json_raises_the_typed_error(self) -> None:
        with pytest.raises(DecisionEngineError) as exc_info:
            await _collect(["data: nope", ""])
        assert exc_info.value.details == {"payload": "nope"}

        with pytest.raises(DecisionEngineError) as exc_info:
            await _collect(["data: nope"])
        assert "trailing" in str(exc_info.value)


class TestStreamModel:
    def test_persists_a_device_binding_token_from_the_stream_response(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/agent/runs/run_1/events").mock(
            return_value=Response(
                200,
                headers={**_SSE_HEADERS, DEVICE_BINDING_TOKEN_HEADER: "bind-token-1"},
                content=b'data: {"type": "agent.run.completed", "run_id": "run_1"}\n\n',
            )
        )

        events = list(client.stream_agent_run_events("run_1"))

        assert len(events) == 1
        assert client._client.headers[DEVICE_BINDING_TOKEN_HEADER] == "bind-token-1"
        assert (
            device_binding.load_device_binding_token(
                base_url=TEST_BASE_URL, api_key=TEST_API_KEY, device_id=derived_test_device_id()
            )
            == "bind-token-1"
        )

    def test_an_empty_stream_yields_nothing(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/agent/runs/run_1/events").mock(
            return_value=Response(200, headers=_SSE_HEADERS, content=b"")
        )

        assert list(client.stream_agent_run_events("run_1")) == []

    def test_an_invalid_event_payload_fails_model_validation(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/agent/runs/run_1/events").mock(
            return_value=Response(
                200, headers=_SSE_HEADERS, content=b'data: {"type": "unknown.event"}\n\n'
            )
        )

        with pytest.raises(ValueError):
            list(client.stream_agent_run_events("run_1"))

    @pytest.mark.asyncio
    async def test_async_stream_persists_the_binding_token(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/agent/runs/run_1/events").mock(
            return_value=Response(
                200,
                headers={**_SSE_HEADERS, DEVICE_BINDING_TOKEN_HEADER: "bind-token-2"},
                content=b'data: {"type": "agent.run.completed", "run_id": "run_1"}\n\n',
            )
        )

        async with AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL) as client:
            events = [event async for event in client.stream_agent_run_events("run_1")]
            assert client._client.headers[DEVICE_BINDING_TOKEN_HEADER] == "bind-token-2"

        assert events[0].type == "agent.run.completed"
        assert (
            device_binding.load_device_binding_token(
                base_url=TEST_BASE_URL, api_key=TEST_API_KEY, device_id=derived_test_device_id()
            )
            == "bind-token-2"
        )

    @pytest.mark.asyncio
    async def test_async_stream_rejects_a_non_event_stream_content_type(self, mock_router) -> None:
        mock_router.get(f"{TEST_BASE_URL}/v1/agent/runs/run_1/events").mock(
            return_value=Response(200, text="plain text")
        )

        async with AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL) as client:
            with pytest.raises(DecisionEngineError) as exc_info:
                _ = [event async for event in client.stream_agent_run_events("run_1")]

        assert exc_info.value.error_code == "invalid_stream_content_type"
        assert exc_info.value.details == {"content_type": "text/plain; charset=utf-8"}
