"""Tests for the LLM facade surface: request shapes and response parsing."""

from __future__ import annotations

import pytest
from httpx import Response

from decision_engine import AlgentaClient

from .conftest import TEST_BASE_URL, derived_test_device_id, request_json


def test_list_models_gets_the_model_catalog(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/models").mock(
        return_value=Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "text.tokenizer",
                        "runtime_module": "tokenizer",
                        "description": "Deterministic tokenizer",
                        "available": True,
                    }
                ],
            },
        )
    )

    result = client.list_models()

    assert route.calls[0].request.method == "GET"
    assert result.object == "list"
    assert result.data[0].id == "text.tokenizer"
    assert result.data[0].available is True


def test_requests_carry_auth_and_device_headers(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.get(f"{TEST_BASE_URL}/v1/models").mock(
        return_value=Response(200, json={"object": "list", "data": []})
    )

    client.list_models()

    headers = route.calls[0].request.headers
    assert headers["Authorization"] == "Bearer de_live_test_key"
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"].startswith("algenta-python/")
    assert headers["X-Algenta-Device-Id"] == derived_test_device_id()


def test_tokenize_posts_model_and_input(client: AlgentaClient, mock_router) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/tokenize").mock(
        return_value=Response(
            200,
            json={
                "model": "text.tokenizer",
                "tokenizer_kind": "hash",
                "tokens": ["hello", "world"],
                "token_count": 2,
            },
        )
    )

    result = client.tokenize("hello world")

    assert request_json(route) == {"model": "text.tokenizer", "input": "hello world"}
    assert result.token_count == 2
    assert result.tokens == ["hello", "world"]


def test_count_tokens_posts_to_the_count_endpoint(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/count_tokens").mock(
        return_value=Response(
            200,
            json={
                "model": "text.tokenizer",
                "tokenizer_kind": "hash",
                "token_count": 3,
            },
        )
    )

    result = client.count_tokens("one two three")

    assert request_json(route) == {"model": "text.tokenizer", "input": "one two three"}
    assert result.token_count == 3


def test_chat_completions_posts_messages_and_tool_configuration(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "id": "chatcmpl_123",
                "model": "text.tokenizer",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Hi there."},
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )
    )
    messages = [{"role": "user", "content": "Say hi"}]
    tools = [{"type": "function", "function": {"name": "get_weather"}}]

    result = client.chat_completions(
        messages,
        model="text.chat",
        tools=tools,
        tool_choice="auto",
        parallel_tool_calls=False,
    )

    assert request_json(route) == {
        "model": "text.chat",
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }
    assert result.choices[0].message.content == "Hi there."
    assert result.usage.total_tokens == 5


def test_chat_completions_omits_unset_tool_arguments(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "id": "chatcmpl_123",
                "model": "text.tokenizer",
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
            },
        )
    )

    client.chat_completions([{"role": "user", "content": "hi"}])

    assert request_json(route) == {
        "model": "text.tokenizer",
        "messages": [{"role": "user", "content": "hi"}],
    }


def test_embeddings_posts_input_and_dimensions(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/embeddings").mock(
        return_value=Response(
            200,
            json={
                "model": "text.hash_embedding_v1",
                "dimensions": 64,
                "data": [{"index": 0, "embedding": [0.1, 0.2], "token_count": 2}],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )
    )

    result = client.embeddings("hello world", dimensions=128)

    assert request_json(route) == {
        "model": "text.hash_embedding_v1",
        "input": "hello world",
        "dimensions": 128,
    }
    assert result.dimensions == 64
    assert result.data[0].embedding == [0.1, 0.2]


def test_embedding_similarity_posts_both_vectors(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/embeddings/similarity").mock(
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

    result = client.embedding_similarity([1.0, 0.0], [0.9, 0.1])

    assert request_json(route) == {
        "model": "embeddings.cosine_similarity",
        "left": [1.0, 0.0],
        "right": [0.9, 0.1],
    }
    assert result.score == pytest.approx(0.99)


def test_rerank_includes_top_n_only_when_provided(
    client: AlgentaClient, mock_router
) -> None:
    route = mock_router.post(f"{TEST_BASE_URL}/v1/rerank").mock(
        return_value=Response(
            200,
            json={
                "model": "embeddings.cosine_similarity",
                "similarity_metric": "cosine",
                "total_documents": 1,
                "returned_documents": 1,
                "data": [{"id": "doc_1", "index": 0, "rank": 0, "score": 0.5}],
            },
        )
    )

    result = client.rerank([0.1], [{"id": "doc_1", "text": "hello"}], top_n=5)

    assert request_json(route) == {
        "model": "embeddings.cosine_similarity",
        "query_embedding": [0.1],
        "documents": [{"id": "doc_1", "text": "hello"}],
        "top_n": 5,
    }
    assert result.data[0].id == "doc_1"
