"""Tests for the facade's lazy surface-module loaders.

The sync and async facades load each surface module (``client_llm_surface``,
``client_job_surface``, ...) through a ``@cache``-d loader on the facade
package. Every mixin module carries a thin wrapper per loader that re-reads the
attribute from the facade on each call, so that a test (or an integration)
monkey-patching ``client_facade._llm_surface_module`` sees the patch take effect
inside the mixin bodies. These tests pin that contract for every wrapper of
every mixin on both facades, and that each loader resolves the module it names.
"""

from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace

import pytest

_FACADES = ["decision_engine.client_facade", "decision_engine.async_client_facade"]

_MIXINS = [
    "_mixin_account_control_plane",
    "_mixin_agent_run",
    "_mixin_connector_repository",
    "_mixin_contract_capability",
    "_mixin_job_deployment",
    "_mixin_llm",
    "_mixin_product_decision",
    "_mixin_simulation_query",
    "_mixin_trigger_source",
]

# loader name -> surface module suffix (the sync facade imports
# ``decision_engine.client_<suffix>``, the async one ``decision_engine.async_client_<suffix>``).
_LOADERS = {
    "_connector_surface_module": "connector_surface",
    "_repository_surface_module": "repository_surface",
    "_query_surface_module": "query_surface",
    "_contract_surface_module": "contract_surface",
    "_simulation_surface_module": "simulation_surface",
    "_source_surface_module": "source_surface",
    "_job_surface_module": "job_surface",
    "_product_surface_module": "product_surface",
    "_deployment_surface_module": "deployment_surface",
    "_account_surface_module": "account_surface",
    "_control_plane_surface_module": "control_plane_surface",
    "_llm_surface_module": "llm_surface",
    "_agent_run_surface_module": "agent_run_surface",
    "_decision_plan_surface_module": "decision_plan_surface",
    "_decision_memory_surface_module": "decision_memory_surface",
    "_trigger_surface_module": "trigger_surface",
    "_capability_plane_surface_module": "capability_plane_surface",
}


def _surface_module_name(facade_name: str, suffix: str) -> str:
    prefix = "async_client_" if facade_name.endswith("async_client_facade") else "client_"
    return f"decision_engine.{prefix}{suffix}"


@pytest.mark.parametrize("facade_name", _FACADES)
@pytest.mark.parametrize(("loader_name", "suffix"), sorted(_LOADERS.items()))
def test_facade_loaders_resolve_the_surface_module_they_name(
    facade_name: str, loader_name: str, suffix: str
) -> None:
    facade = importlib.import_module(facade_name)

    module = getattr(facade, loader_name)()

    assert isinstance(module, ModuleType)
    assert module.__name__ == _surface_module_name(facade_name, suffix)
    # The loaders are cached: the same module object comes back every time.
    assert getattr(facade, loader_name)() is module


@pytest.mark.parametrize("facade_name", _FACADES)
@pytest.mark.parametrize("mixin_name", _MIXINS)
def test_every_mixin_wrapper_delegates_to_the_facade_loader(
    facade_name: str, mixin_name: str
) -> None:
    facade = importlib.import_module(facade_name)
    mixin = importlib.import_module(f"{facade_name}.{mixin_name}")

    for loader_name in _LOADERS:
        assert getattr(mixin, loader_name)() is getattr(facade, loader_name)(), loader_name


@pytest.mark.parametrize("facade_name", _FACADES)
@pytest.mark.parametrize("mixin_name", _MIXINS)
def test_every_mixin_wrapper_sees_a_facade_monkeypatch(
    monkeypatch: pytest.MonkeyPatch, facade_name: str, mixin_name: str
) -> None:
    """The documented reason the wrappers exist: patches on the facade propagate."""
    facade = importlib.import_module(facade_name)
    mixin = importlib.import_module(f"{facade_name}.{mixin_name}")

    for loader_name in _LOADERS:
        sentinel = SimpleNamespace(patched=loader_name)
        monkeypatch.setattr(facade, loader_name, lambda sentinel=sentinel: sentinel)

        assert getattr(mixin, loader_name)() is sentinel, loader_name


def test_the_sync_and_async_facades_expose_the_same_loader_set() -> None:
    sync_facade = importlib.import_module(_FACADES[0])
    async_facade = importlib.import_module(_FACADES[1])

    sync_loaders = {name for name in dir(sync_facade) if name.endswith("_surface_module")}
    async_loaders = {name for name in dir(async_facade) if name.endswith("_surface_module")}

    assert sync_loaders == async_loaders == set(_LOADERS)
