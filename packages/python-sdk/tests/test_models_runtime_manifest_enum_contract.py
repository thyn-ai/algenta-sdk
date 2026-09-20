# SPDX-License-Identifier: Apache-2.0

"""Observable-behaviour pins for the ``Runtime*Result`` enums and the page iterators.

The runtime-manifest result enums are ``str``-valued enums, so their members are
compared, hashed, JSON-encoded and validated by *value*. Everything in
``TestEnumValueSemantics`` and ``TestWireFormat`` must hold whether the classes are
spelled ``class X(str, Enum)`` or ``class X(StrEnum)``: it pins the wire format and
the comparison semantics the SDK's users rely on.

``TestEnumTextForm`` pins the one thing that *does* differ between the two spellings
(``str()`` / ``format()`` of a member), and ``TestValidateModelRoundTrip`` pins its
one user-visible consequence inside this SDK: ``model_loader.validate_model`` on an
already-parsed model whose enum-keyed mappings are non-empty.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator, Iterator
from enum import Enum

import pytest
from pydantic import ValidationError as PydanticValidationError

from decision_engine import model_loader
from decision_engine.connector_surface_common import (
    iter_page_items,
    iter_page_items_async,
)
from decision_engine.models_runtime_manifest import _enums
from decision_engine.models_runtime_manifest._enums import (
    RuntimeBenchmarkClassCodeResult,
    RuntimeMaturityResult,
    RuntimeModuleIdResult,
    _ensure_unique_runtime_values,
)
from decision_engine.models_runtime_manifest._models_admin import RuntimeAdminModulesResult
from decision_engine.models_runtime_manifest._models_release_top import RuntimeManifestResult

from .conftest import make_runtime_admin_modules_payload, make_runtime_manifest_payload

# Every public enum class, derived from the module's own export list so a class added
# to (or removed from) ``_enums.py`` is covered without touching this file.
ENUM_CLASSES: tuple[type[Enum], ...] = tuple(
    getattr(_enums, name)
    for name in _enums.__all__
    if isinstance(getattr(_enums, name), type) and issubclass(getattr(_enums, name), Enum)
)


def _class_id(cls: type[Enum]) -> str:
    return cls.__name__


def test_every_export_is_a_str_valued_enum_class() -> None:
    assert len(ENUM_CLASSES) == len(_enums.__all__)
    assert ENUM_CLASSES, "the export list must not be empty"
    for cls in ENUM_CLASSES:
        assert issubclass(cls, str), cls.__name__
        assert issubclass(cls, Enum), cls.__name__
        assert len(cls) >= 1, cls.__name__


class TestEnumValueSemantics:
    """Value-based equality, hashing, lookup and encoding -- identical for both spellings."""

    @pytest.mark.parametrize("cls", ENUM_CLASSES, ids=_class_id)
    def test_members_equal_and_hash_like_their_values(self, cls: type[Enum]) -> None:
        for member in cls:
            assert member == member.value, member.name
            assert hash(member) == hash(member.value), member.name
            assert member in {member.value: 1}, member.name
            assert member.value in {member: 1}, member.name

    @pytest.mark.parametrize("cls", ENUM_CLASSES, ids=_class_id)
    def test_members_json_encode_as_their_values(self, cls: type[Enum]) -> None:
        for member in cls:
            assert json.dumps(member) == json.dumps(member.value), member.name

    @pytest.mark.parametrize("cls", ENUM_CLASSES, ids=_class_id)
    def test_value_lookup_returns_the_singleton_member(self, cls: type[Enum]) -> None:
        for member in cls:
            assert cls(member.value) is member, member.name

    @pytest.mark.parametrize("cls", ENUM_CLASSES, ids=_class_id)
    def test_repr_names_class_member_and_value(self, cls: type[Enum]) -> None:
        for member in cls:
            assert repr(member) == f"<{cls.__name__}.{member.name}: {member.value!r}>"

    @pytest.mark.parametrize("cls", ENUM_CLASSES, ids=_class_id)
    def test_values_are_unique_within_the_class(self, cls: type[Enum]) -> None:
        values = [member.value for member in cls]

        assert len(values) == len(set(values))

    def test_ensure_unique_dedupes_a_name_ne_value_enum_by_value(self) -> None:
        # ``microkernel_latency`` is spelled "B1" on the wire: the dedupe must see the
        # value form, otherwise a bare "B1" would slip past as a distinct entry.
        assert RuntimeBenchmarkClassCodeResult.microkernel_latency.value == "B1"
        with pytest.raises(ValueError, match=r"classes must be unique; duplicate entries: B1$"):
            _ensure_unique_runtime_values(
                [RuntimeBenchmarkClassCodeResult.microkernel_latency, "B1"], "classes"
            )


class TestWireFormat:
    """What leaves the SDK as JSON: bare values, never ``ClassName.member`` -- both spellings."""

    def test_manifest_json_dump_emits_enum_values(self) -> None:
        payload = make_runtime_manifest_payload()
        manifest = RuntimeManifestResult.model_validate(payload)

        dumped = manifest.model_dump(mode="json")

        assert dumped["deployment_mode"] == "saas"
        assert dumped["shipping_contract"]["runtime_core_layer"] == "mojo_llm_runtime_core"
        assert dumped["signature"]["algorithm"] == "hmac-sha256"
        assert dumped["signature"]["scope"] == "control_plane_hmac_v1"
        assert RuntimeManifestResult.model_validate(dumped) == manifest

    def test_manifest_enum_keyed_maturity_map_dumps_value_keys(self) -> None:
        manifest = RuntimeManifestResult.model_validate(make_runtime_manifest_payload())
        populated = manifest.model_copy(
            update={
                "maturity": {
                    RuntimeModuleIdResult.embeddings: RuntimeMaturityResult.enterprise_ready
                }
            }
        )

        dumped = populated.model_dump(mode="json")

        assert dumped["maturity"] == {"embeddings": "enterprise_ready"}
        assert populated.model_dump()["maturity"] == {
            RuntimeModuleIdResult.embeddings: RuntimeMaturityResult.enterprise_ready
        }

    def test_admin_modules_summary_counts_dump_value_keys(self) -> None:
        result = RuntimeAdminModulesResult.model_validate(make_runtime_admin_modules_payload())

        dumped = result.model_dump(mode="json")

        assert dumped["summary"]["maturity_counts"] == {"benchmarked": 1, "enterprise_ready": 1}
        assert dumped["summary"]["layer_counts"] == {"mojo_llm_runtime_core": 2}

    @pytest.mark.parametrize(
        ("model", "payload_factory"),
        [
            (RuntimeManifestResult, make_runtime_manifest_payload),
            (RuntimeAdminModulesResult, make_runtime_admin_modules_payload),
        ],
        ids=["manifest", "admin-modules"],
    )
    def test_json_text_never_contains_a_class_qualified_member(
        self, model: type, payload_factory: object
    ) -> None:
        parsed = model.model_validate(payload_factory())  # type: ignore[operator]

        text = parsed.model_dump_json()

        assert '"Runtime' not in text
        assert "Result." not in text
        assert model.model_validate_json(text) == parsed

    def test_json_schema_keeps_enums_as_string_typed_value_lists(self) -> None:
        schema = RuntimeManifestResult.model_json_schema()

        maturity = schema["$defs"]["RuntimeMaturityResult"]

        assert maturity["type"] == "string"
        assert maturity["enum"] == [member.value for member in RuntimeMaturityResult]
        for cls in ENUM_CLASSES:
            definition = schema["$defs"].get(cls.__name__)
            if definition is None:
                continue  # not every enum is reachable from the manifest model
            assert definition["type"] == "string", cls.__name__
            assert definition["enum"] == [member.value for member in cls], cls.__name__


class TestEnumTextForm:
    """``str()`` / ``format()`` of a member: the one observable difference between spellings.

    Today the classes are ``class X(str, Enum)``: on Python 3.11+ that renders the
    class-qualified name (``RuntimeMaturityResult.benchmarked``), not the wire value.
    """

    @pytest.mark.parametrize("cls", ENUM_CLASSES, ids=_class_id)
    def test_str_and_format_render_the_class_qualified_name(self, cls: type[Enum]) -> None:
        for member in cls:
            qualified = f"{cls.__name__}.{member.name}"

            assert str(member) == qualified
            assert f"{member}" == qualified
            assert format(member) == qualified
            assert member.value != qualified  # the two forms really are distinct


class TestValidateModelRoundTrip:
    """``validate_model`` on a parsed model: the in-SDK consequence of the text form.

    ``model_loader._normalize_validation_payload`` rebuilds mapping keys with ``str()``;
    with ``class X(str, Enum)`` an enum key becomes ``"RuntimeMaturityResult.benchmarked"``
    and re-validation of a non-empty enum-keyed map fails. Pinned here as current
    behaviour so the fix, when it lands, is a visible expectation change.
    """

    def test_normalisation_renders_enum_keys_with_str(self) -> None:
        normalized = model_loader._normalize_validation_payload(
            {RuntimeMaturityResult.benchmarked: 1}
        )

        assert normalized == {"RuntimeMaturityResult.benchmarked": 1}

    def test_revalidating_admin_modules_rejects_class_qualified_count_keys(self) -> None:
        parsed = RuntimeAdminModulesResult.model_validate(make_runtime_admin_modules_payload())

        with pytest.raises(PydanticValidationError, match="RuntimeMaturityResult.benchmarked"):
            model_loader.validate_model("RuntimeAdminModulesResult", parsed)

    def test_revalidating_a_manifest_with_a_populated_maturity_map_fails(self) -> None:
        manifest = RuntimeManifestResult.model_validate(make_runtime_manifest_payload())
        populated = manifest.model_copy(
            update={
                "maturity": {
                    RuntimeModuleIdResult.embeddings: RuntimeMaturityResult.enterprise_ready
                }
            }
        )

        with pytest.raises(PydanticValidationError, match="RuntimeModuleIdResult.embeddings"):
            model_loader.validate_model("RuntimeManifestResult", populated)

    def test_revalidating_a_manifest_with_an_empty_maturity_map_round_trips(self) -> None:
        manifest = RuntimeManifestResult.model_validate(make_runtime_manifest_payload())

        again = model_loader.validate_model("RuntimeManifestResult", manifest)

        assert again == manifest
        assert again is not manifest


class TestPageIteratorTypingContract:
    """Public typing contract of the two generic page iterators."""

    @pytest.mark.parametrize(
        ("function", "origin"),
        [(iter_page_items, Iterator), (iter_page_items_async, AsyncIterator)],
        ids=["sync", "async"],
    )
    def test_keyword_only_parameters_and_return_annotation(
        self, function: object, origin: type
    ) -> None:
        signature = inspect.signature(function)  # type: ignore[arg-type]

        assert list(signature.parameters) == [
            "page",
            "limit",
            "max_items",
            "fetch_page",
            "items_attr",
        ]
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in signature.parameters.values()
        )
        assert signature.return_annotation == f"{origin.__name__}[ItemT]"

    def test_type_variables_are_module_level_typevars(self) -> None:
        # Current spelling: ``PageT = TypeVar("PageT")`` / ``ItemT = TypeVar("ItemT")`` at module
        # scope (PEP 484), unbound and unconstrained, and not generic per PEP 695.
        from decision_engine import connector_surface_common

        for name in ("PageT", "ItemT"):
            type_variable = getattr(connector_surface_common, name)
            assert type_variable.__name__ == name
            assert type_variable.__bound__ is None
            assert type_variable.__constraints__ == ()
        assert iter_page_items.__type_params__ == ()
        assert iter_page_items_async.__type_params__ == ()
