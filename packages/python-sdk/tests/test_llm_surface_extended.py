"""Tests for the LLM surface beyond the basics: artifact bridge, responses, streaming.

``test_llm_surface.py`` covers models, tokenize, count_tokens, chat completions,
embeddings, similarity and rerank on the sync client. This module adds the
artifact-bridge resolver, the Responses API (with every optional tool argument),
both Server-Sent Events streams, and exercises the whole LLM surface on the
async facade.
"""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.exceptions import DecisionEngineError, ValidationError
from decision_engine.models_llm import (
    ChatCompletionsStreamChunkResult,
    ResponseStreamEventResult,
)

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response, request_json

_ARTIFACT_RESOLUTION = {
    "backend": "huggingface_hub",
    "artifact_backend": "local_cache",
    "repo_id": "algenta/text-tokenizer",
    "filename": "tokenizer.json",
    "local_files_only": True,
    "status": "resolved",
    "cache_root": "/var/cache/algenta",
    "auth_env_vars": ["HF_TOKEN"],
    "auth_configured": False,
    "resolved_path": "/var/cache/algenta/tokenizer.json",
}

_RESPONSE = {
    "id": "resp_1",
    "model": "text.tokenizer",
    "output": [
        {
            "id": "out_1",
            "index": 0,
            "content": [
                {"type": "tokenization", "tokens": ["hello", "world"], "token_count": 2},
            ],
        }
    ],
    "usage": {"prompt_tokens": 2, "total_tokens": 2},
}

_CHAT_SSE = (
    b'data: {"id": "cmpl_1", "model": "text.tokenizer", "choices": '
    b'[{"index": 0, "delta": {"role": "assistant", "content": "hel"}}]}\n\n'
    b'data: {"id": "cmpl_1", "model": "text.tokenizer", "choices": '
    b'[{"index": 0, "delta": {"content": "lo"}, "finish_reason": "stop"}]}\n\n'
    b"data: [DONE]\n\n"
)

_RESPONSES_SSE = (
    b'data: {"type": "response.created", "response": {"id": "resp_1", '
    b'"status": "in_progress", "model": "text.tokenizer"}}\n\n'
    b'data: {"type": "response.output_item.done", "output_index": 0, "item": '
    b'{"id": "out_1", "index": 0, "content": '
    b'[{"type": "text", "text": "hi", "token_count": 1}]}}\n\n'
    b'data: {"type": "response.completed", "response": {"id": "resp_1", '
    b'"status": "completed", "model": "text.tokenizer", '
    b'"usage": {"prompt_tokens": 1, "total_tokens": 2}}}\n\n'
)

_SSE_HEADERS = {"content-type": "text/event-stream; charset=utf-8"}


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestArtifactBridge:
    def test_posts_the_resolution_request_without_a_revision(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/artifacts/resolve").mock(
            return_value=Response(200, json=_ARTIFACT_RESOLUTION)
        )

        result = client.resolve_artifact_bridge(
            repo_id="algenta/text-tokenizer", filename="tokenizer.json"
        )

        assert request_json(route) == {
            "repo_id": "algenta/text-tokenizer",
            "filename": "tokenizer.json",
            "local_files_only": True,
        }
        assert result.status == "resolved"
        assert result.resolved_path == "/var/cache/algenta/tokenizer.json"
        assert result.revision is None

    def test_includes_the_revision_when_given(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/artifacts/resolve").mock(
            return_value=Response(
                200, json={**_ARTIFACT_RESOLUTION, "revision": "v2", "status": "not_cached"}
            )
        )

        result = client.resolve_artifact_bridge(
            repo_id="algenta/text-tokenizer",
            filename="tokenizer.json",
            revision="v2",
            local_files_only=False,
        )

        assert request_json(route)["revision"] == "v2"
        assert request_json(route)["local_files_only"] is False
        assert result.status == "not_cached"


class TestResponses:
    def test_posts_the_defaults(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/responses").mock(
            return_value=Response(200, json=_RESPONSE)
        )

        result = client.responses("hello world")

        assert request_json(route) == {
            "model": "text.tokenizer",
            "input": "hello world",
            "dimensions": 64,
        }
        assert result.status == "completed"
        assert result.output[0].content[0].tokens == ["hello", "world"]
        assert result.usage.total_tokens == 2

    def test_posts_every_optional_tool_argument(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/responses").mock(
            return_value=Response(200, json=_RESPONSE)
        )
        tools = [{"type": "function", "function": {"name": "lookup"}}]

        client.responses(
            [{"role": "user", "content": "hi"}],
            model="chat.default",
            dimensions=128,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=False,
            previous_response_id="resp_0",
        )

        assert request_json(route) == {
            "model": "chat.default",
            "input": [{"role": "user", "content": "hi"}],
            "dimensions": 128,
            "tools": tools,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "previous_response_id": "resp_0",
        }


class TestStreaming:
    def test_stream_chat_completions_yields_typed_chunks(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/chat/completions").mock(
            return_value=Response(200, headers=_SSE_HEADERS, content=_CHAT_SSE)
        )

        chunks = list(
            client.stream_chat_completions(
                [{"role": "user", "content": "hi"}],
                tools=[{"type": "function"}],
                tool_choice="none",
            )
        )

        body = request_json(route)
        assert body["stream"] is True
        assert body["tools"] == [{"type": "function"}]
        assert body["tool_choice"] == "none"
        assert "parallel_tool_calls" not in body
        assert route.calls[0].request.headers["Accept"] == "text/event-stream"
        assert all(isinstance(chunk, ChatCompletionsStreamChunkResult) for chunk in chunks)
        assert "".join(chunk.choices[0].delta.content or "" for chunk in chunks) == "hello"
        assert chunks[-1].choices[0].finish_reason == "stop"

    def test_stream_responses_yields_lifecycle_events(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/responses").mock(
            return_value=Response(200, headers=_SSE_HEADERS, content=_RESPONSES_SSE)
        )

        events = list(client.stream_responses("hi", previous_response_id="resp_0"))

        body = request_json(route)
        assert body["stream"] is True
        assert body["previous_response_id"] == "resp_0"
        assert [event.type for event in events] == [
            "response.created",
            "response.output_item.done",
            "response.completed",
        ]
        assert all(isinstance(event, ResponseStreamEventResult) for event in events)
        assert events[1].item is not None and events[1].item.content[0].text == "hi"
        assert events[2].response is not None and events[2].response.usage is not None

    def test_stream_rejects_a_non_event_stream_content_type(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/chat/completions").mock(
            return_value=Response(200, json={"id": "cmpl_1", "model": "m", "choices": []})
        )

        with pytest.raises(DecisionEngineError) as exc_info:
            list(client.stream_chat_completions([{"role": "user", "content": "hi"}]))

        assert exc_info.value.error_code == "invalid_stream_content_type"
        assert exc_info.value.details == {"content_type": "application/json"}

    def test_stream_errors_raise_the_typed_exception_for_the_status(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/responses").mock(
            return_value=error_response(422, message="bad input", code="invalid_input")
        )

        with pytest.raises(ValidationError) as exc_info:
            list(no_retry_client.stream_responses("hi"))

        assert exc_info.value.status_code == 422


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_request_response_methods(self, mock_router) -> None:
        tokenize = mock_router.post(f"{TEST_BASE_URL}/v1/tokenize").mock(
            return_value=Response(
                200,
                json={
                    "model": "text.tokenizer",
                    "tokenizer_kind": "hash",
                    "tokens": ["a"],
                    "token_count": 1,
                },
            )
        )
        mock_router.post(f"{TEST_BASE_URL}/v1/count_tokens").mock(
            return_value=Response(
                200, json={"model": "text.tokenizer", "tokenizer_kind": "hash", "token_count": 3}
            )
        )
        bridge = mock_router.post(f"{TEST_BASE_URL}/v1/artifacts/resolve").mock(
            return_value=Response(200, json={**_ARTIFACT_RESOLUTION, "revision": "main"})
        )
        chat = mock_router.post(f"{TEST_BASE_URL}/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "cmpl_1",
                    "model": "text.tokenizer",
                    "choices": [{"index": 0, "message": {"content": "hello"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        )
        responses = mock_router.post(f"{TEST_BASE_URL}/v1/responses").mock(
            return_value=Response(200, json=_RESPONSE)
        )
        embeddings = mock_router.post(f"{TEST_BASE_URL}/v1/embeddings").mock(
            return_value=Response(
                200,
                json={
                    "model": "text.hash_embedding_v1",
                    "dimensions": 4,
                    "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4], "token_count": 2}],
                    "usage": {"prompt_tokens": 2, "total_tokens": 2},
                },
            )
        )
        similarity = mock_router.post(f"{TEST_BASE_URL}/v1/embeddings/similarity").mock(
            return_value=Response(
                200,
                json={
                    "model": "embeddings.cosine_similarity",
                    "similarity_metric": "cosine",
                    "score": 0.99,
                    "dimension": 2,
                },
            )
        )
        rerank = mock_router.post(f"{TEST_BASE_URL}/v1/rerank").mock(
            return_value=Response(
                200,
                json={
                    "model": "embeddings.cosine_similarity",
                    "similarity_metric": "cosine",
                    "total_documents": 1,
                    "returned_documents": 1,
                    "data": [{"id": "doc_1", "index": 0, "rank": 1, "score": 0.9}],
                },
            )
        )

        async with _async_client() as client:
            tokens = await client.tokenize("a", model="text.tokenizer")
            count = await client.count_tokens("a b c")
            resolved = await client.resolve_artifact_bridge(
                repo_id="algenta/text-tokenizer", filename="tokenizer.json", revision="main"
            )
            completion = await client.chat_completions(
                [{"role": "user", "content": "hi"}], parallel_tool_calls=True
            )
            response = await client.responses("hi", dimensions=32, tool_choice="required")
            vectors = await client.embeddings(["a", "b"], dimensions=4)
            score = await client.embedding_similarity([1.0, 0.0], [1.0, 0.0])
            ranked = await client.rerank([0.1, 0.2], [{"id": "doc_1", "text": "x"}], top_n=1)

        assert request_json(tokenize) == {"model": "text.tokenizer", "input": "a"}
        assert tokens.token_count == 1 and count.token_count == 3
        assert request_json(bridge)["revision"] == "main"
        assert resolved.revision == "main"
        assert request_json(chat)["parallel_tool_calls"] is True
        assert completion.choices[0].message.content == "hello"
        assert request_json(responses) == {
            "model": "text.tokenizer",
            "input": "hi",
            "dimensions": 32,
            "tool_choice": "required",
        }
        assert response.id == "resp_1"
        assert request_json(embeddings) == {
            "model": "text.hash_embedding_v1",
            "input": ["a", "b"],
            "dimensions": 4,
        }
        assert vectors.data[0].embedding == [0.1, 0.2, 0.3, 0.4]
        assert request_json(similarity)["left"] == [1.0, 0.0]
        assert score.score == pytest.approx(0.99)
        assert request_json(rerank)["top_n"] == 1
        assert ranked.data[0].rank == 1

    @pytest.mark.asyncio
    async def test_rerank_omits_top_n_when_unset(self, mock_router) -> None:
        route = mock_router.post(f"{TEST_BASE_URL}/v1/rerank").mock(
            return_value=Response(
                200,
                json={
                    "model": "embeddings.cosine_similarity",
                    "similarity_metric": "cosine",
                    "total_documents": 0,
                    "returned_documents": 0,
                },
            )
        )

        async with _async_client() as client:
            await client.rerank([0.1], [])

        assert "top_n" not in request_json(route)

    @pytest.mark.asyncio
    async def test_streams_yield_typed_events(self, mock_router) -> None:
        chat = mock_router.post(f"{TEST_BASE_URL}/v1/chat/completions").mock(
            return_value=Response(200, headers=_SSE_HEADERS, content=_CHAT_SSE)
        )
        mock_router.post(f"{TEST_BASE_URL}/v1/responses").mock(
            return_value=Response(200, headers=_SSE_HEADERS, content=_RESPONSES_SSE)
        )

        async with _async_client() as client:
            chunks = [
                chunk
                async for chunk in client.stream_chat_completions(
                    [{"role": "user", "content": "hi"}], parallel_tool_calls=False
                )
            ]
            events = [event async for event in client.stream_responses(["a", "b"], tools=[])]

        assert request_json(chat)["parallel_tool_calls"] is False
        assert "".join(chunk.choices[0].delta.content or "" for chunk in chunks) == "hello"
        assert [event.type for event in events][-1] == "response.completed"

    @pytest.mark.asyncio
    async def test_stream_rejects_a_non_event_stream_content_type(self, mock_router) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/responses").mock(
            return_value=Response(200, json=_RESPONSE)
        )

        async with _async_client() as client:
            with pytest.raises(DecisionEngineError) as exc_info:
                _ = [event async for event in client.stream_responses("hi")]

        assert exc_info.value.error_code == "invalid_stream_content_type"

    @pytest.mark.asyncio
    async def test_stream_errors_raise_the_typed_exception_for_the_status(
        self, mock_router
    ) -> None:
        mock_router.post(f"{TEST_BASE_URL}/v1/chat/completions").mock(
            return_value=error_response(422, message="bad messages")
        )

        async with _async_client() as client:
            with pytest.raises(ValidationError) as exc_info:
                _ = [chunk async for chunk in client.stream_chat_completions([])]

        assert exc_info.value.status_code == 422
