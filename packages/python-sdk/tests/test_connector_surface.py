"""Tests for the connector and dataset surface and its shared request helpers.

``connector_surface_common`` builds the payloads (dropping ``None`` fields),
normalises list responses into paginated envelopes, and drives page iteration
for ``iter_connectors``/``iter_datasets``. The surface tests pin each method's
request shape on both facades; the iteration tests pin the page-walking rules
(stop at the last page, stop on an empty page, honour ``max_items``).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import Response

from decision_engine import AlgentaClient, AsyncAlgentaClient
from decision_engine.connector_surface_common import (
    build_connect_data_payload,
    build_create_connector_payload,
    build_dataset_list_params,
    build_preview_connector_payload,
    build_update_connector_payload,
    iter_page_items,
    iter_page_items_async,
    normalize_paginated_items_payload,
)
from decision_engine.exceptions import NotFoundError

from .conftest import TEST_API_KEY, TEST_BASE_URL, error_response, request_json

_CONNECTORS = f"{TEST_BASE_URL}/v1/connectors"
_DATA = f"{TEST_BASE_URL}/v1/data"

_CONNECTOR = {
    "id": "conn_1",
    "name": "warehouse",
    "connector_type": "postgres",
    "status": "active",
    "visibility": "private",
}

_TEST_INFO = {"success": True, "message": "connected", "latency_ms": 42}

_BROWSE = {
    "connector_type": "postgres",
    "items": [{"table": "orders"}],
    "total": 1,
    "message": "1 table",
}


def _connector(index: int) -> dict[str, Any]:
    return {**_CONNECTOR, "id": f"conn_{index}", "name": f"connector-{index}"}


def _dataset(index: int) -> dict[str, Any]:
    return {"dataset_id": f"ds_{index}", "dataset_name": f"dataset-{index}"}


def _connector_page(items: list[dict[str, Any]], *, page: int, pages: int, limit: int) -> dict:
    return {
        "connectors": items,
        "total": pages * limit,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def _dataset_page(items: list[dict[str, Any]], *, page: int, pages: int, limit: int) -> dict:
    return {
        "datasets": items,
        "count": len(items),
        "total": pages * limit,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def _async_client() -> AsyncAlgentaClient:
    return AsyncAlgentaClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL, max_retries=0)


class TestPayloadBuilders:
    def test_create_payload_drops_none_fields(self) -> None:
        assert build_create_connector_payload(name="w", connector_type="postgres") == {
            "name": "w",
            "connector_type": "postgres",
        }
        assert build_create_connector_payload(
            name="w",
            connector_type="postgres",
            config={"dsn": "x"},
            description="d",
            visibility="org",
        ) == {
            "name": "w",
            "connector_type": "postgres",
            "config": {"dsn": "x"},
            "description": "d",
            "visibility": "org",
        }

    def test_update_payload_is_empty_when_nothing_changes(self) -> None:
        assert build_update_connector_payload() == {}
        assert build_update_connector_payload(name="renamed", config={}) == {
            "name": "renamed",
            "config": {},
        }

    def test_preview_payload_drops_a_missing_config(self) -> None:
        assert build_preview_connector_payload(connector_type="csv") == {"connector_type": "csv"}
        assert build_preview_connector_payload(connector_type="csv", config={"path": "a.csv"}) == {
            "connector_type": "csv",
            "config": {"path": "a.csv"},
        }

    def test_connect_data_payload_merges_kwargs_over_the_request(self) -> None:
        payload = build_connect_data_payload(
            {"source": "orders.csv", "name": None, "mode": "replace"},
            {"name": "orders", "mode": None},
        )

        assert payload == {"source": "orders.csv", "mode": "replace", "name": "orders"}

    def test_connect_data_payload_accepts_no_request(self) -> None:
        assert build_connect_data_payload(None, {"source": "x"}) == {"source": "x"}

    def test_dataset_list_params_only_carry_set_filters(self) -> None:
        assert build_dataset_list_params(page=1, limit=50) == {"page": 1, "limit": 50}
        assert build_dataset_list_params(
            page=2, limit=10, search="orders", status="ready", source_name="crm", compact=True
        ) == {
            "page": 2,
            "limit": 10,
            "search": "orders",
            "status": "ready",
            "source_name": "crm",
            "compact": "1",
        }
        assert "compact" not in build_dataset_list_params(page=1, limit=1, compact=False)


class TestPaginationNormalisation:
    def test_a_list_becomes_a_single_page(self) -> None:
        payload = normalize_paginated_items_payload(
            [_connector(1), _connector(2)],
            items_key="connectors",
            context="Connector list response",
            requested_page=1,
        )

        assert payload == {
            "connectors": [_connector(1), _connector(2)],
            "total": 2,
            "page": 1,
            "limit": 2,
            "pages": 1,
        }

    def test_an_empty_list_uses_a_unit_limit_and_can_carry_a_count(self) -> None:
        payload = normalize_paginated_items_payload(
            [],
            items_key="datasets",
            context="Dataset list response",
            requested_page=None,
            count_key="count",
        )

        assert payload == {
            "datasets": [],
            "total": 0,
            "page": 1,
            "limit": 1,
            "pages": 1,
            "count": 0,
        }

    def test_a_list_is_rejected_beyond_the_first_page(self) -> None:
        with pytest.raises(ValueError, match="returned a raw list for page=2"):
            normalize_paginated_items_payload(
                [], items_key="connectors", context="Connector list response", requested_page=2
            )

    def test_an_envelope_passes_through_when_its_items_are_a_list(self) -> None:
        envelope = _connector_page([_connector(1)], page=1, pages=1, limit=200)

        assert (
            normalize_paginated_items_payload(
                envelope, items_key="connectors", context="ctx", requested_page=1
            )
            is envelope
        )

    def test_an_envelope_without_a_list_field_is_rejected(self) -> None:
        with pytest.raises(
            ValueError, match="must be a JSON object with a list 'connectors' field"
        ):
            normalize_paginated_items_payload(
                {"connectors": None}, items_key="connectors", context="ctx", requested_page=1
            )

    def test_scalars_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a JSON array or paginated object"):
            normalize_paginated_items_payload(
                "nope", items_key="connectors", context="ctx", requested_page=1
            )


class _Page:
    def __init__(self, items: list[int], pages: int) -> None:
        self.items = items
        self.pages = pages


class TestPageIteration:
    def test_walks_every_page_and_stops_at_the_last(self) -> None:
        pages = {1: _Page([1, 2], 3), 2: _Page([3, 4], 3), 3: _Page([5], 3)}
        fetched: list[tuple[int, int]] = []

        def fetch(page: int, limit: int) -> _Page:
            fetched.append((page, limit))
            return pages[page]

        items = list(
            iter_page_items(page=1, limit=2, max_items=None, fetch_page=fetch, items_attr="items")
        )

        assert items == [1, 2, 3, 4, 5]
        assert fetched == [(1, 2), (2, 2), (3, 2)]

    def test_stops_after_max_items_without_fetching_further(self) -> None:
        fetched: list[int] = []

        def fetch(page: int, limit: int) -> _Page:
            fetched.append(page)
            return _Page([1, 2, 3], 9)

        items = list(
            iter_page_items(page=1, limit=3, max_items=2, fetch_page=fetch, items_attr="items")
        )

        assert items == [1, 2]
        assert fetched == [1]

    def test_stops_on_an_empty_page_even_if_more_are_advertised(self) -> None:
        def fetch(page: int, limit: int) -> _Page:
            return _Page([], 5)

        assert (
            list(
                iter_page_items(
                    page=2, limit=3, max_items=None, fetch_page=fetch, items_attr="items"
                )
            )
            == []
        )

    @pytest.mark.asyncio
    async def test_async_iteration_walks_pages_and_honours_max_items(self) -> None:
        pages = {1: _Page([1, 2], 2), 2: _Page([3, 4], 2)}
        fetched: list[int] = []

        async def fetch(page: int, limit: int) -> _Page:
            fetched.append(page)
            return pages[page]

        everything = [
            item
            async for item in iter_page_items_async(
                page=1, limit=2, max_items=None, fetch_page=fetch, items_attr="items"
            )
        ]
        capped = [
            item
            async for item in iter_page_items_async(
                page=1, limit=2, max_items=3, fetch_page=fetch, items_attr="items"
            )
        ]

        assert everything == [1, 2, 3, 4]
        assert capped == [1, 2, 3]
        assert fetched == [1, 2, 1, 2]


class TestConnectorCrud:
    def test_create_connector_posts_the_trimmed_payload(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(_CONNECTORS).mock(return_value=Response(200, json=_CONNECTOR))

        result = client.create_connector(
            name="warehouse", connector_type="postgres", config={"dsn": "postgres://x"}
        )

        assert request_json(route) == {
            "name": "warehouse",
            "connector_type": "postgres",
            "config": {"dsn": "postgres://x"},
        }
        assert result.id == "conn_1"

    def test_list_connectors_sends_pagination_and_parses_the_page(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_CONNECTORS).mock(
            return_value=Response(
                200, json=_connector_page([_connector(1)], page=2, pages=3, limit=1)
            )
        )

        result = client.list_connectors(page=2, limit=1)

        assert dict(route.calls[0].request.url.params) == {"page": "2", "limit": "1"}
        assert result.connectors[0].id == "conn_1"
        assert result.pages == 3

    def test_list_connectors_accepts_a_bare_list_on_the_first_page(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_CONNECTORS).mock(return_value=Response(200, json=[_connector(1)]))

        result = client.list_connectors()

        assert result.total == 1 and result.pages == 1

    def test_list_connectors_rejects_a_bare_list_beyond_the_first_page(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_CONNECTORS).mock(return_value=Response(200, json=[_connector(1)]))

        with pytest.raises(ValueError, match="returned a raw list for page=2"):
            client.list_connectors(page=2)

    def test_get_update_test_browse_and_delete(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(f"{_CONNECTORS}/conn_1").mock(return_value=Response(200, json=_CONNECTOR))
        update = mock_router.patch(f"{_CONNECTORS}/conn_1").mock(
            return_value=Response(200, json={**_CONNECTOR, "name": "renamed"})
        )
        mock_router.post(f"{_CONNECTORS}/conn_1/test").mock(
            return_value=Response(200, json=_TEST_INFO)
        )
        mock_router.get(f"{_CONNECTORS}/conn_1/browse").mock(
            return_value=Response(200, json=_BROWSE)
        )
        delete = mock_router.delete(f"{_CONNECTORS}/conn_1").mock(return_value=Response(204))

        assert client.get_connector("conn_1").name == "warehouse"
        assert client.update_connector("conn_1", name="renamed", visibility="org").name == "renamed"
        assert request_json(update) == {"name": "renamed", "visibility": "org"}
        assert client.test_connector("conn_1").latency_ms == 42
        assert client.browse_connector("conn_1").items == [{"table": "orders"}]
        assert client.delete_connector("conn_1") is None
        assert delete.call_count == 1

    def test_preview_test_and_browse_post_the_connector_definition(
        self, client: AlgentaClient, mock_router
    ) -> None:
        test = mock_router.post(f"{_CONNECTORS}/test").mock(
            return_value=Response(200, json=_TEST_INFO)
        )
        browse = mock_router.post(f"{_CONNECTORS}/browse").mock(
            return_value=Response(200, json=_BROWSE)
        )

        client.preview_test_connector(connector_type="postgres", config={"dsn": "x"})
        client.preview_browse_connector(connector_type="postgres")

        assert request_json(test) == {"connector_type": "postgres", "config": {"dsn": "x"}}
        assert request_json(browse) == {"connector_type": "postgres"}

    def test_iter_connectors_walks_pages_until_the_last(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_CONNECTORS).mock(
            side_effect=[
                Response(
                    200,
                    json=_connector_page([_connector(1), _connector(2)], page=1, pages=2, limit=2),
                ),
                Response(200, json=_connector_page([_connector(3)], page=2, pages=2, limit=2)),
            ]
        )

        ids = [connector.id for connector in client.iter_connectors(limit=2)]

        assert ids == ["conn_1", "conn_2", "conn_3"]
        assert [dict(call.request.url.params) for call in route.calls] == [
            {"page": "1", "limit": "2"},
            {"page": "2", "limit": "2"},
        ]

    def test_iter_connectors_honours_max_items(self, client: AlgentaClient, mock_router) -> None:
        mock_router.get(_CONNECTORS).mock(
            return_value=Response(
                200, json=_connector_page([_connector(1), _connector(2)], page=1, pages=4, limit=2)
            )
        )

        assert [c.id for c in client.iter_connectors(limit=2, max_items=1)] == ["conn_1"]


class TestDatasets:
    def test_connect_data_merges_request_and_kwargs(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.post(f"{_DATA}/connect").mock(
            return_value=Response(
                200,
                json={"status": "connected", "dataset_id": "ds_1", "schema": {"columns": ["a"]}},
            )
        )

        result = client.connect_data({"source": "orders.csv"}, name="orders", visibility=None)

        assert request_json(route) == {"source": "orders.csv", "name": "orders"}
        assert result.dataset_id == "ds_1"
        assert result.schema == {"columns": ["a"]}

    def test_list_datasets_sends_every_filter(self, client: AlgentaClient, mock_router) -> None:
        route = mock_router.get(_DATA).mock(
            return_value=Response(200, json=_dataset_page([_dataset(1)], page=1, pages=1, limit=10))
        )

        result = client.list_datasets(
            limit=10, search="orders", status="ready", source_name="crm", compact=True
        )

        assert dict(route.calls[0].request.url.params) == {
            "page": "1",
            "limit": "10",
            "search": "orders",
            "status": "ready",
            "source_name": "crm",
            "compact": "1",
        }
        assert result.datasets[0].dataset_id == "ds_1"

    def test_list_datasets_accepts_a_bare_list_and_fills_the_count(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(_DATA).mock(return_value=Response(200, json=[_dataset(1), _dataset(2)]))

        result = client.list_datasets()

        assert result.count == 2 and result.total == 2

    def test_iter_datasets_walks_pages_and_forwards_filters(
        self, client: AlgentaClient, mock_router
    ) -> None:
        route = mock_router.get(_DATA).mock(
            side_effect=[
                Response(200, json=_dataset_page([_dataset(1)], page=1, pages=2, limit=1)),
                Response(200, json=_dataset_page([_dataset(2)], page=2, pages=2, limit=1)),
            ]
        )

        names = [
            d.dataset_name for d in client.iter_datasets(limit=1, search="orders", compact=True)
        ]

        assert names == ["dataset-1", "dataset-2"]
        first = dict(route.calls[0].request.url.params)
        assert first == {"page": "1", "limit": "1", "search": "orders", "compact": "1"}
        assert route.calls[1].request.url.params["page"] == "2"

    def test_dataset_detail_summary_refresh_and_delete(
        self, client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_DATA}/ds_1").mock(
            return_value=Response(200, json={"dataset": _dataset(1), "schema": {"columns": ["a"]}})
        )
        mock_router.get(f"{_DATA}/ds_1/summary").mock(
            return_value=Response(
                200,
                json={
                    "dataset_id": "ds_1",
                    "name": "dataset-1",
                    "status": "ready",
                    "column_count": 1,
                },
            )
        )
        refresh = mock_router.post(f"{_DATA}/ds_1/refresh").mock(
            return_value=Response(200, json={"status": "refreshing", "dataset_id": "ds_1"})
        )
        mock_router.delete(f"{_DATA}/ds_1").mock(
            return_value=Response(
                200, json={"dataset_id": "ds_1", "status": "deleted", "connection_deleted": True}
            )
        )

        detail = client.get_dataset("ds_1")
        summary = client.get_dataset_summary("ds_1")
        refreshed = client.refresh_dataset("ds_1")
        deleted = client.delete_dataset("ds_1")

        assert detail.dataset.dataset_id == "ds_1" and detail.schema == {"columns": ["a"]}
        assert summary.column_count == 1
        assert refresh.calls[0].request.method == "POST"
        assert refreshed.status == "refreshing"
        assert deleted.connection_deleted is True

    def test_not_found_surfaces_as_the_typed_error(
        self, no_retry_client: AlgentaClient, mock_router
    ) -> None:
        mock_router.get(f"{_DATA}/missing").mock(
            return_value=error_response(404, message="dataset not found")
        )

        with pytest.raises(NotFoundError, match="dataset not found"):
            no_retry_client.get_dataset("missing")


class TestAsyncParity:
    @pytest.mark.asyncio
    async def test_connector_crud(self, mock_router) -> None:
        create = mock_router.post(_CONNECTORS).mock(return_value=Response(200, json=_CONNECTOR))
        listing = mock_router.get(_CONNECTORS).mock(
            side_effect=[
                Response(200, json=[_connector(1)]),
                Response(200, json=_connector_page([_connector(1)], page=1, pages=2, limit=1)),
                Response(200, json=_connector_page([_connector(2)], page=2, pages=2, limit=1)),
            ]
        )
        mock_router.get(f"{_CONNECTORS}/conn_1").mock(return_value=Response(200, json=_CONNECTOR))
        update = mock_router.patch(f"{_CONNECTORS}/conn_1").mock(
            return_value=Response(200, json={**_CONNECTOR, "description": "d"})
        )
        mock_router.post(f"{_CONNECTORS}/conn_1/test").mock(
            return_value=Response(200, json=_TEST_INFO)
        )
        preview_test = mock_router.post(f"{_CONNECTORS}/test").mock(
            return_value=Response(200, json=_TEST_INFO)
        )
        mock_router.get(f"{_CONNECTORS}/conn_1/browse").mock(
            return_value=Response(200, json=_BROWSE)
        )
        preview_browse = mock_router.post(f"{_CONNECTORS}/browse").mock(
            return_value=Response(200, json=_BROWSE)
        )
        delete = mock_router.delete(f"{_CONNECTORS}/conn_1").mock(return_value=Response(204))

        async with _async_client() as client:
            created = await client.create_connector(name="warehouse", connector_type="postgres")
            page = await client.list_connectors()
            iterated = [c.id async for c in client.iter_connectors(limit=1)]
            fetched = await client.get_connector("conn_1")
            updated = await client.update_connector("conn_1", description="d")
            tested = await client.test_connector("conn_1")
            previewed = await client.preview_test_connector(connector_type="postgres")
            browsed = await client.browse_connector("conn_1")
            preview_browsed = await client.preview_browse_connector(
                connector_type="postgres", config={"dsn": "x"}
            )
            assert await client.delete_connector("conn_1") is None

        assert request_json(create) == {"name": "warehouse", "connector_type": "postgres"}
        assert created.id == "conn_1"
        assert page.total == 1
        assert iterated == ["conn_1", "conn_2"]
        assert listing.call_count == 3
        assert fetched.name == "warehouse"
        assert request_json(update) == {"description": "d"}
        assert updated.description == "d"
        assert tested.success is True and previewed.success is True
        assert request_json(preview_test) == {"connector_type": "postgres"}
        assert browsed.total == 1 and preview_browsed.total == 1
        assert request_json(preview_browse) == {
            "connector_type": "postgres",
            "config": {"dsn": "x"},
        }
        assert delete.call_count == 1

    @pytest.mark.asyncio
    async def test_dataset_operations(self, mock_router) -> None:
        connect = mock_router.post(f"{_DATA}/connect").mock(
            return_value=Response(200, json={"status": "connected", "dataset_id": "ds_1"})
        )
        listing = mock_router.get(_DATA).mock(
            side_effect=[
                Response(200, json=_dataset_page([_dataset(1)], page=1, pages=2, limit=1)),
                Response(200, json=_dataset_page([_dataset(2)], page=2, pages=2, limit=1)),
            ]
        )
        mock_router.get(f"{_DATA}/ds_1").mock(
            return_value=Response(200, json={"dataset": _dataset(1)})
        )
        mock_router.get(f"{_DATA}/ds_1/summary").mock(
            return_value=Response(
                200,
                json={
                    "dataset_id": "ds_1",
                    "name": "dataset-1",
                    "status": "ready",
                    "column_count": 3,
                },
            )
        )
        mock_router.post(f"{_DATA}/ds_1/refresh").mock(
            return_value=Response(200, json={"status": "refreshing"})
        )
        mock_router.delete(f"{_DATA}/ds_1").mock(
            return_value=Response(200, json={"dataset_id": "ds_1", "status": "deleted"})
        )

        async with _async_client() as client:
            connected = await client.connect_data(source="orders.csv")
            names = [d.dataset_name async for d in client.iter_datasets(limit=1, status="ready")]
            detail = await client.get_dataset("ds_1")
            summary = await client.get_dataset_summary("ds_1")
            refreshed = await client.refresh_dataset("ds_1")
            deleted = await client.delete_dataset("ds_1")

        assert request_json(connect) == {"source": "orders.csv"}
        assert connected.dataset_id == "ds_1"
        assert names == ["dataset-1", "dataset-2"]
        assert listing.calls[0].request.url.params["status"] == "ready"
        assert detail.schema == {}
        assert summary.column_count == 3
        assert refreshed.status == "refreshing"
        assert deleted.connection_deleted is False

    @pytest.mark.asyncio
    async def test_list_datasets_rejects_a_bare_list_beyond_the_first_page(
        self, mock_router
    ) -> None:
        mock_router.get(_DATA).mock(return_value=Response(200, json=[_dataset(1)]))

        async with _async_client() as client:
            with pytest.raises(ValueError, match="returned a raw list for page=3"):
                await client.list_datasets(page=3)

    @pytest.mark.asyncio
    async def test_not_found_surfaces_as_the_typed_error(self, mock_router) -> None:
        mock_router.get(f"{_CONNECTORS}/missing").mock(
            return_value=error_response(404, message="connector not found")
        )

        async with _async_client() as client:
            with pytest.raises(NotFoundError, match="connector not found"):
                await client.get_connector("missing")
