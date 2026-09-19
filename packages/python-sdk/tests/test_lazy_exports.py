"""Tests for the SDK's lazy compatibility modules.

Several public modules (``decision_engine.models``, ``decision_engine.client``,
the ``models_*`` shims, the flat ``client_service_surface`` and
``request_helpers``) are thin re-export tables resolved on first attribute
access through a module-level ``__getattr__``. These tests pin the contract
those modules share: every name in ``__all__`` resolves to the very object
exported by its source module, the resolved value is cached on the shim,
``dir()`` advertises the exports, and unknown names raise ``AttributeError``.

The model loader that powers ``validate_model`` is covered alongside, since
it is the same lazy table in a different shape.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest
from pydantic import BaseModel

from decision_engine import model_loader

_LAZY_MODULES = [
    "decision_engine.models",
    "decision_engine.models_query",
    "decision_engine.models_simulation",
    "decision_engine.models_connectors",
    "decision_engine.models_run_metadata",
    "decision_engine.models_percentile_summary",
    "decision_engine.models_metrics_summary",
    "decision_engine.client",
    "decision_engine.async_client",
    "decision_engine.request_helpers",
    "decision_engine.client_service_surface",
    "decision_engine.async_client_service_surface",
    "decision_engine.client_decision_surface",
    "decision_engine.async_client_decision_surface",
]


def _lazy_table(module: ModuleType) -> dict[str, tuple[str, str]]:
    return module._LAZY_EXPORTS


@pytest.mark.parametrize("module_name", _LAZY_MODULES)
def test_every_export_resolves_to_the_source_object(module_name: str) -> None:
    module = importlib.import_module(module_name)
    table = _lazy_table(module)

    assert table, f"{module_name} advertises no lazy exports"
    for export_name, (source_module_name, attribute_name) in table.items():
        source = importlib.import_module(source_module_name)
        expected = getattr(source, attribute_name)

        assert getattr(module, export_name) is expected, export_name
        # Resolution is cached on the shim: a second lookup does not go back
        # through __getattr__ (the name now lives in the module globals).
        assert module.__dict__[export_name] is expected


@pytest.mark.parametrize("module_name", _LAZY_MODULES)
def test_all_and_dir_advertise_every_lazy_export(module_name: str) -> None:
    module = importlib.import_module(module_name)
    table = _lazy_table(module)

    assert set(table) <= set(module.__all__)
    assert set(table) <= set(dir(module))


@pytest.mark.parametrize("module_name", _LAZY_MODULES)
def test_unknown_names_raise_attribute_error_naming_the_module(module_name: str) -> None:
    module = importlib.import_module(module_name)

    with pytest.raises(AttributeError, match=module_name):
        _ = module.definitely_not_an_export


def test_request_helpers_exposes_the_default_constants_eagerly() -> None:
    from decision_engine import request_helpers, sdk_defaults

    assert request_helpers.DEFAULT_TIMEOUT == sdk_defaults.DEFAULT_TIMEOUT
    assert request_helpers.DEFAULT_MAX_RETRIES == sdk_defaults.DEFAULT_MAX_RETRIES
    assert request_helpers.DEFAULT_JOIN_PATH_HOPS == sdk_defaults.DEFAULT_JOIN_PATH_HOPS
    assert request_helpers.MAX_JOIN_PATH_HOPS == sdk_defaults.MAX_JOIN_PATH_HOPS


def test_client_module_caches_every_contract_constant_on_first_access() -> None:
    """Touching one contract export primes the rest, so later lookups are attribute reads."""
    from decision_engine import _contract, client

    assert client.DEFAULT_BASE_URL == _contract.DEFAULT_BASE_URL
    for name in client._CONTRACT_EXPORT_NAMES:
        assert name in client.__dict__, name


def test_service_surface_flattens_every_facade_surface() -> None:
    """The flat service surface points at the same functions the facade dispatches to."""
    from decision_engine import (
        client_account_surface,
        client_job_surface,
        client_query_surface,
        client_service_surface,
    )

    assert client_service_surface.query is client_query_surface.query
    assert client_service_surface.poll_job is client_job_surface.poll_job
    assert client_service_surface.create_api_key is client_account_surface.create_api_key


class TestModelLoader:
    def test_every_registered_model_loads_as_a_pydantic_class(self) -> None:
        for model_name in model_loader._MODEL_EXPORTS:
            model = model_loader._load_model(model_name)
            assert isinstance(model, type) and issubclass(model, BaseModel), model_name
            assert model.__name__ == model_name

    def test_unknown_model_names_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported model name: NoSuchModel"):
            model_loader.validate_model("NoSuchModel", {})

    def test_validate_model_accepts_a_model_instance_as_payload(self) -> None:
        """Re-validating an already-parsed model normalises it back to plain data first."""
        from decision_engine.models_control_plane import BillingSessionResult

        parsed = BillingSessionResult.model_validate({"url": "https://billing.example.com"})

        again = model_loader.validate_model("BillingSessionResult", parsed)

        assert again == parsed
        assert again is not parsed

    def test_normalisation_recurses_through_mappings_lists_and_tuples(self) -> None:
        from decision_engine.models_control_plane import BillingSessionResult

        nested = {
            "a": [BillingSessionResult.model_validate({"url": "https://x.example"})],
            "b": (1, {"c": BillingSessionResult.model_validate({"url": "https://y.example"})}),
        }

        normalized = model_loader._normalize_validation_payload(nested)

        assert normalized == {
            "a": [{"url": "https://x.example"}],
            "b": (1, {"c": {"url": "https://y.example"}}),
        }

    def test_validate_model_list_validates_each_item(self) -> None:
        results = model_loader.validate_model_list(
            "BillingSessionResult",
            [{"url": "https://one.example"}, {"url": "https://two.example"}],
        )

        assert [item.url for item in results] == ["https://one.example", "https://two.example"]
