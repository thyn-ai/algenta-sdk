"""Property-based tests (Hypothesis) for the SDK's pure helpers.

The example-based suite pins down specific behaviours; these tests state the
invariants that must hold for *every* input to the parsers, validators,
normalisers and URL/config helpers that run on each request: round-trips,
idempotence, order and length guarantees, and "never crashes on arbitrary
input". Every property is capped at a small number of examples, has no
per-example deadline (CI runner timing is noisy) and is derandomised so a CI
run is reproducible; raise ``max_examples`` locally when hunting for bugs.
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any
from unittest import mock
from urllib.parse import urlparse

import httpx
import pytest

# CI installs hypothesis from .github/requirements/python-sdk-ci.txt; the package's own `[dev]`
# extra (mirrored from thyn-ai/algenta) may not carry it yet, so a contributor following
# CONTRIBUTING.md (`pip install -e ".[dev]" && pytest`) skips this module instead of failing
# collection.
pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from pydantic import ValidationError as PydanticValidationError
from pydantic import create_model

import decision_engine.transport_retry_policy as retry_policy
from decision_engine import device_binding
from decision_engine._contract import (
    ALGENTA_OWNED_HOSTS,
    ALGENTA_OWNED_SUFFIXES,
    DEFAULT_BASE_URL,
)
from decision_engine.contract_fallback import (
    _endpoint_suffix,
    _merge_contract_sections,
    _rebase_endpoint,
)
from decision_engine.device_binding import (
    _binding_store_key,
    load_device_binding_token,
    store_device_binding_token,
)
from decision_engine.device_headers import (
    _DEVICE_ID_MAX_LENGTH,
    _DEVICE_ID_MIN_LENGTH,
    _PLATFORM_MAX_LENGTH,
    _PLATFORM_VERSION_MAX_LENGTH,
    _SDK_VERSION_MAX_LENGTH,
    DEVICE_ID_HEADER,
    HOSTNAME_HASH_HEADER,
    PLATFORM_HEADER,
    PLATFORM_VERSION_HEADER,
    SDK_VERSION_HEADER,
    _derived_device_id_from_seed,
    _fingerprint_hash,
    _validate_device_id,
    build_device_headers,
)
from decision_engine.exceptions import (
    AuthenticationError,
    DecisionEngineError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from decision_engine.privacy_profile import (
    _join_url_path,
    _parse_optional_bool,
    cloud_disabled,
    is_algenta_owned_base_url,
    normalize_base_url,
    resolve_client_base_url,
)
from decision_engine.request_common import _strip_none
from decision_engine.request_query_helpers import (
    DEFAULT_JOIN_PATH_HOPS,
    MAX_JOIN_PATH_HOPS,
    _dedupe_strings,
    _normalize_query_like_request,
    _request_source_set,
    _split_resolved_sources,
)
from decision_engine.request_simulation_helpers import (
    _normalize_compare_request,
    _normalize_expert_variable,
    _normalize_recommend_request,
    _normalize_simulation_request,
)
from decision_engine.transport_response import handle_response
from decision_engine.transport_retry_policy import (
    DEFAULT_RETRY_AFTER_SECONDS,
    RATE_LIMIT_BACKOFF_BASE_SECONDS,
    SERVER_ERROR_BACKOFF_BASE_SECONDS,
    parse_retry_after_header,
    rate_limit_backoff_seconds,
    server_error_backoff_seconds,
)
from decision_engine.validation_error_details import (
    _KNOWN_PYDANTIC_ERROR_PREFIXES,
    build_validation_error_details,
)

# Fast and reproducible: a bounded number of examples per property, no
# per-example deadline, and a fixed seed derived from the test name so CI never
# fails on an input a previous run did not see. Bugs are hunted locally with
# `--hypothesis-seed` / a higher max_examples, not on the PR gate.
_FAST = settings(max_examples=100, deadline=None, derandomize=True)

_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")

# --- shared strategies -------------------------------------------------------

_IDENTIFIER = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)
_FINITE = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e15, max_value=1e15)
_SCALAR = st.one_of(st.none(), st.booleans(), st.integers(), _FINITE, st.text())
# Arbitrary JSON documents (no NaN/inf: they are not JSON).
_JSON = st.recursive(
    _SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(max_size=5), children, max_size=3),
    ),
    max_leaves=12,
)

# RFC 1123-ish host labels: lowercase alphanumerics, inner hyphens allowed.
_LABEL = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,20}[a-z0-9])?", fullmatch=True)
_HOSTNAME = st.lists(_LABEL, min_size=1, max_size=4).map(".".join)
_UNOWNED_HOST = _HOSTNAME.filter(
    lambda host: host not in ALGENTA_OWNED_HOSTS and not host.endswith(ALGENTA_OWNED_SUFFIXES)
)
_OWNED_HOST = st.one_of(
    st.sampled_from(ALGENTA_OWNED_HOSTS),
    st.builds(
        lambda prefix, suffix: f"{prefix}{suffix}",
        _HOSTNAME,
        st.sampled_from(ALGENTA_OWNED_SUFFIXES),
    ),
)
_URL_PATH = st.lists(st.from_regex(r"[a-z0-9._-]{1,10}", fullmatch=True), max_size=3).map(
    lambda parts: "".join(f"/{part}" for part in parts)
)


@st.composite
def absolute_urls(draw, host=_HOSTNAME, path=_URL_PATH) -> str:  # noqa: ANN001
    """An absolute http(s) URL with an optional port and path, never a trailing slash."""
    scheme = draw(st.sampled_from(["http", "https"]))
    hostname = draw(host)
    port = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=65535)))
    netloc = hostname if port is None else f"{hostname}:{port}"
    return f"{scheme}://{netloc}{draw(path)}"


_SELF_HOSTED_URL = absolute_urls(host=_UNOWNED_HOST)
_ALGENTA_CLOUD_URL = absolute_urls(host=_OWNED_HOST)


# --- transport_retry_policy ---------------------------------------------------


class TestRetryAfterHeader:
    @_FAST
    @given(st.text())
    def test_any_header_value_parses_to_a_non_negative_int(self, value: str) -> None:
        seconds = parse_retry_after_header(value)
        assert isinstance(seconds, int)
        assert seconds >= 0

    @_FAST
    @given(st.integers(min_value=-(10**9), max_value=10**9))
    def test_delta_seconds_round_trip_clamped_at_zero(self, seconds: int) -> None:
        # A negative delta means "retry now", never a negative sleep.
        assert parse_retry_after_header(str(seconds)) == max(seconds, 0)
        assert parse_retry_after_header(f"  {seconds}\t") == max(seconds, 0)

    @_FAST
    @given(st.integers(min_value=-(10**6), max_value=10**6))
    def test_http_date_round_trip(self, delta: int) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        header = format_datetime(now + timedelta(seconds=delta), usegmt=True)
        with mock.patch.object(retry_policy, "utc_now", return_value=now):
            assert parse_retry_after_header(header) == max(delta, 0)

    @_FAST
    @given(st.text(alphabet=" \t\r\n"), st.integers(min_value=0, max_value=10**6))
    def test_blank_values_fall_back_to_the_default(self, blank: str, default: int) -> None:
        assert parse_retry_after_header(blank, default_seconds=default) == default
        assert parse_retry_after_header(None, default_seconds=default) == default
        assert parse_retry_after_header(None) == DEFAULT_RETRY_AFTER_SECONDS


class TestBackoffSchedule:
    @_FAST
    @given(st.integers(min_value=0, max_value=30))
    def test_server_error_backoff_doubles_every_attempt(self, attempt: int) -> None:
        assert server_error_backoff_seconds(attempt=0) == SERVER_ERROR_BACKOFF_BASE_SECONDS
        doubled = 2 * server_error_backoff_seconds(attempt=attempt)
        assert server_error_backoff_seconds(attempt=attempt + 1) == doubled

    @_FAST
    @given(st.integers(min_value=1, max_value=10**6), st.integers(min_value=0, max_value=30))
    def test_a_positive_retry_after_overrides_the_schedule(
        self, retry_after: int, attempt: int
    ) -> None:
        assert rate_limit_backoff_seconds(retry_after, attempt=attempt) == float(retry_after)

    @_FAST
    @given(
        st.one_of(st.none(), st.integers(max_value=0)),
        st.integers(min_value=0, max_value=30),
    )
    def test_missing_or_non_positive_retry_after_uses_the_doubling_schedule(
        self, retry_after: int | None, attempt: int
    ) -> None:
        expected = rate_limit_backoff_seconds(None, attempt=attempt)
        assert rate_limit_backoff_seconds(retry_after, attempt=attempt) == expected
        assert rate_limit_backoff_seconds(None, attempt=0) == RATE_LIMIT_BACKOFF_BASE_SECONDS
        assert rate_limit_backoff_seconds(None, attempt=attempt + 1) == 2 * expected


# --- request payload helpers --------------------------------------------------


class TestStripNone:
    @_FAST
    @given(st.dictionaries(st.text(), _SCALAR))
    def test_drops_exactly_the_none_values_and_is_idempotent(
        self, values: dict[str, Any]
    ) -> None:
        stripped = _strip_none(values)
        assert None not in stripped.values()
        # Every surviving item is an unchanged input item...
        assert stripped.items() <= values.items()
        # ...and nothing but the None-valued ones went missing, in input order.
        assert list(stripped) == [key for key, value in values.items() if value is not None]
        assert _strip_none(stripped) == stripped


class TestSourceNames:
    _SOURCE_NAME = (
        st.text(min_size=1).map(str.strip).filter(lambda name: bool(name) and "⋈" not in name)
    )

    @_FAST
    @given(st.lists(st.text()))
    def test_dedupe_strips_drops_blanks_and_keeps_first_occurrence_order(
        self, values: list[str]
    ) -> None:
        deduped = _dedupe_strings(values)
        assert len(set(deduped)) == len(deduped)
        assert all(item and item == item.strip() for item in deduped)
        assert set(deduped) == {value.strip() for value in values if value.strip()}
        stripped = [value.strip() for value in values]
        first_positions = [stripped.index(item) for item in deduped]
        assert first_positions == sorted(first_positions)
        assert _dedupe_strings(deduped) == deduped

    @_FAST
    @given(st.lists(_SOURCE_NAME, min_size=1, unique=True))
    def test_split_resolved_sources_inverts_the_join_operator(self, names: list[str]) -> None:
        assert _split_resolved_sources(" ⋈ ".join(names)) == names
        assert _split_resolved_sources("⋈".join(names)) == names
        assert _split_resolved_sources(None) == []
        assert _split_resolved_sources("") == []


_JOIN_EDGE = st.fixed_dictionaries({"left_source": _IDENTIFIER, "right_source": _IDENTIFIER})
_VALID_HOPS = st.integers(min_value=1, max_value=MAX_JOIN_PATH_HOPS)
# bool is an int subclass, so True/False are (valid) hop counts; they are not
# generated here on purpose.
_INVALID_HOPS = st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=MAX_JOIN_PATH_HOPS + 1),
    st.floats(),
    st.text(),
    st.none(),
)


@st.composite
def query_like_payloads(draw) -> dict[str, Any]:  # noqa: ANN001
    payload: dict[str, Any] = {"question": draw(st.text(max_size=20))}
    if draw(st.booleans()):
        join_path: dict[str, Any] = {"base_source": draw(_IDENTIFIER)}
        max_hops = DEFAULT_JOIN_PATH_HOPS
        if draw(st.booleans()):
            max_hops = draw(_VALID_HOPS)
            join_path["max_hops"] = max_hops
        join_path["edges"] = draw(st.lists(_JOIN_EDGE, max_size=max_hops))
        payload["join_path"] = join_path
    if draw(st.booleans()):
        payload["constraints"] = {
            "max_join_hops": draw(_VALID_HOPS),
            "read_only": draw(st.booleans()),
        }
    return payload


@st.composite
def source_requests(draw) -> tuple[dict[str, Any], list[str]]:  # noqa: ANN001
    """A query request plus every source name it mentions (in field order)."""
    request: dict[str, Any] = {"question": draw(st.text(max_size=20))}
    mentioned: list[str] = []
    for key in ("source_name", "join_source_name"):
        if draw(st.booleans()):
            name = draw(_IDENTIFIER)
            request[key] = name
            mentioned.append(name)
    if draw(st.booleans()):
        names = draw(st.lists(_IDENTIFIER, max_size=3))
        # Non-source entries must be ignored, not crash the walk.
        request["sources"] = [{"name": name} for name in names] + [{"kind": "junk"}, "junk"]
        mentioned.extend(names)
    if draw(st.booleans()):
        join_path: dict[str, Any] = {}
        for key in ("base_source", "group_source"):
            if draw(st.booleans()):
                name = draw(_IDENTIFIER)
                join_path[key] = name
                mentioned.append(name)
        edges = draw(st.lists(_JOIN_EDGE, max_size=3))
        join_path["edges"] = [*edges, "junk"]
        for edge in edges:
            mentioned.extend((edge["left_source"], edge["right_source"]))
        request["join_path"] = join_path
    return request, mentioned


class TestQueryLikeRequests:
    @_FAST
    @given(query_like_payloads())
    def test_normalisation_is_idempotent_and_never_mutates_its_input(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = deepcopy(payload)
        normalized = _normalize_query_like_request(payload)
        assert payload == snapshot
        assert _normalize_query_like_request(normalized) == normalized
        assert set(normalized) == set(payload)
        if "join_path" in payload:
            join_path = normalized["join_path"]
            assert join_path is not payload["join_path"]
            assert 1 <= join_path["max_hops"] <= MAX_JOIN_PATH_HOPS
            assert join_path["max_hops"] == payload["join_path"].get(
                "max_hops", DEFAULT_JOIN_PATH_HOPS
            )
            assert join_path["edges"] == payload["join_path"]["edges"]
        if "constraints" in payload:
            assert normalized["constraints"] == payload["constraints"]

    @_FAST
    @given(_INVALID_HOPS)
    def test_out_of_range_hop_counts_are_rejected_wherever_they_appear(self, hops: Any) -> None:
        with pytest.raises(ValueError, match="join_path.max_hops"):
            _normalize_query_like_request({"join_path": {"max_hops": hops}})
        with pytest.raises(ValueError, match="constraints.max_join_hops"):
            _normalize_query_like_request({"constraints": {"max_join_hops": hops}})

    @_FAST
    @given(_VALID_HOPS, st.integers(min_value=1, max_value=5))
    def test_more_edges_than_hops_is_rejected(self, max_hops: int, extra: int) -> None:
        edges = [{"left_source": "a", "right_source": "b"}] * (max_hops + extra)
        with pytest.raises(ValueError, match="join_path.edges"):
            _normalize_query_like_request({"join_path": {"max_hops": max_hops, "edges": edges}})

    @_FAST
    @given(source_requests())
    def test_source_set_is_exactly_the_mentioned_names_without_duplicates(
        self, request_and_names: tuple[dict[str, Any], list[str]]
    ) -> None:
        request, mentioned = request_and_names
        source_set = _request_source_set(request)
        assert len(set(source_set)) == len(source_set)
        assert set(source_set) == set(mentioned)
        # Feeding the answer back in as the request's `sources` is a fixed point.
        assert _request_source_set({"sources": [{"name": n} for n in source_set]}) == source_set


# --- request_simulation_helpers -----------------------------------------------

_DISTRIBUTION = st.sampled_from(["fixed", "normal", "uniform", "triangular", "lognormal"])
_EXPERT_VARIABLE = st.fixed_dictionaries(
    {"name": _IDENTIFIER, "distribution": _DISTRIBUTION},
    optional={
        "mean": _FINITE,
        "std": _FINITE,
        "std_dev": _FINITE,
        "low": _FINITE,
        "mode": _FINITE,
        "high": _FINITE,
        "value": _FINITE,
        "min": _FINITE,
        "max": _FINITE,
        "p": _FINITE,
        "shape": _FINITE,
        "scale": _FINITE,
        "params": st.dictionaries(_IDENTIFIER, _FINITE),
    },
)
_RUN_CONTROLS = {
    "runs": st.integers(min_value=1, max_value=10**6),
    "seed": st.integers(),
    "simulation_model": _IDENTIFIER,
}
_AUTO_PAYLOAD = st.fixed_dictionaries(
    {"variables": st.dictionaries(_IDENTIFIER, _FINITE, min_size=1)},
    optional={"objective": _IDENTIFIER, **_RUN_CONTROLS},
)
_EXPERT_PAYLOAD = st.fixed_dictionaries(
    {"variables": st.lists(_EXPERT_VARIABLE, min_size=1, max_size=4)},
    optional={"objective_function": _IDENTIFIER, **_RUN_CONTROLS},
)
_SIMULATION_PAYLOAD = st.one_of(_AUTO_PAYLOAD, _EXPERT_PAYLOAD)
_OPTION = st.fixed_dictionaries(
    {},
    optional={
        "label": _IDENTIFIER,
        "name": _IDENTIFIER,
        "expected_value": _FINITE,
        "risk": st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
    },
)


class TestSimulationRequests:
    @_FAST
    @given(_EXPERT_VARIABLE)
    def test_expert_variables_keep_their_explicit_parameters(
        self, variable: dict[str, Any]
    ) -> None:
        normalized = _normalize_expert_variable(variable)
        assert set(normalized) == {"name", "distribution", "params"}
        assert normalized["name"] == variable["name"]
        assert normalized["distribution"] == variable["distribution"]
        params = normalized["params"]
        if "params" in variable:
            # An explicit params block wins outright and is copied, not aliased.
            assert params == variable["params"]
            assert params is not variable["params"]
            return
        assert None not in params.values()
        for key in ("mean", "low", "mode", "high", "value", "min", "max", "p", "shape", "scale"):
            assert params.get(key) == variable.get(key)
        # `std` falls back to the legacy `std_dev` spelling. The helper tests
        # truthiness, so a literal 0.0 std is treated like an absent one.
        if variable.get("std"):
            assert params["std"] == variable["std"]
        elif variable.get("std_dev"):
            assert params["std"] == variable["std_dev"]

    @_FAST
    @given(_SIMULATION_PAYLOAD)
    def test_normalisation_is_idempotent_and_preserves_run_controls(
        self, payload: dict[str, Any]
    ) -> None:
        snapshot = deepcopy(payload)
        normalized = _normalize_simulation_request(payload)
        assert payload == snapshot
        assert _normalize_simulation_request(normalized) == normalized
        assert normalized["runs"] == payload.get("runs", 10_000)
        for key in ("seed", "simulation_model"):
            assert (key in normalized) == (key in payload)
            assert normalized.get(key) == payload.get(key)
        variables = payload["variables"]
        if isinstance(variables, dict):
            assert normalized["mode"] == "auto"
            assert normalized["scenario"]["variables"] == variables
            expected_objective = payload.get("objective", "maximize_net_value")
            assert normalized["scenario"]["objective"] == expected_objective
        else:
            assert normalized["mode"] == "expert"
            names = [variable["name"] for variable in variables]
            simulation = normalized["simulation"]
            assert [variable["name"] for variable in simulation["variables"]] == names
            assert simulation["objective_function"] == payload.get(
                "objective_function", " + ".join(names)
            )

    @_FAST
    @given(
        st.lists(_SIMULATION_PAYLOAD, min_size=1, max_size=3),
        st.lists(st.one_of(st.none(), _IDENTIFIER), min_size=3, max_size=3),
        st.integers(min_value=1, max_value=10**5),
    )
    def test_compare_wraps_every_scenario_and_is_idempotent(
        self, scenarios: list[dict[str, Any]], labels: list[str | None], runs: int
    ) -> None:
        labelled = [
            {**scenario, "label": label} if label else dict(scenario)
            for scenario, label in zip(scenarios, labels, strict=False)
        ]
        normalized = _normalize_compare_request(labelled, runs=runs)
        assert normalized["runs"] == runs
        assert len(normalized["scenarios"]) == len(labelled)
        for idx, (entry, scenario) in enumerate(
            zip(normalized["scenarios"], labelled, strict=True), start=1
        ):
            assert entry["name"] == scenario.get("label", f"scenario_{idx}")
            bare = {key: value for key, value in scenario.items() if key != "label"}
            assert entry["request"] == _normalize_simulation_request(bare)
        assert _normalize_compare_request(normalized) == normalized

    @_FAST
    @given(st.lists(_OPTION, min_size=1, max_size=4), st.integers(min_value=1, max_value=10**5))
    def test_recommend_options_become_well_ordered_triangular_actions(
        self, options: list[dict[str, Any]], runs: int
    ) -> None:
        normalized = _normalize_recommend_request({"options": options, "runs": runs})
        assert normalized["runs"] == runs
        assert len(normalized["actions"]) == len(options)
        for idx, (action, option) in enumerate(
            zip(normalized["actions"], options, strict=True), start=1
        ):
            assert action["name"] == (option.get("label") or option.get("name") or f"option_{idx}")
            assert action["request"]["runs"] == runs
            (variable,) = action["request"]["simulation"]["variables"]
            params = variable["params"]
            # The spread is at least 1.0, so the triangle is never degenerate.
            assert params["low"] < params["mode"] < params["high"]
            assert params["mode"] == float(option.get("expected_value") or 0.0)
        assert _normalize_recommend_request(normalized) == normalized


# --- privacy_profile: URL and environment handling ----------------------------

_TRUE_WORDS = ("1", "true", "yes", "on")
_FALSE_WORDS = ("0", "false", "no", "off")


class TestBaseUrlNormalisation:
    @_FAST
    @given(absolute_urls(), st.text(alphabet=" \t\r\n"), st.integers(min_value=0, max_value=3))
    def test_clean_urls_are_fixed_points_and_padding_is_ignored(
        self, url: str, padding: str, slashes: int
    ) -> None:
        normalized = normalize_base_url(url, component="test")
        assert normalized == url
        padded = f"{padding}{url}{'/' * slashes}{padding}"
        assert normalize_base_url(padded, component="test") == normalized
        assert normalize_base_url(normalized, component="test") == normalized

    @_FAST
    @given(st.text())
    def test_arbitrary_text_is_either_rejected_or_an_absolute_url(self, text: str) -> None:
        try:
            normalized = normalize_base_url(text, component="test")
        except ValueError:
            return
        parsed = urlparse(normalized)
        assert parsed.scheme
        assert parsed.hostname
        assert not normalized.endswith("/")
        assert normalized == normalized.strip()

    @_FAST
    @given(_ALGENTA_CLOUD_URL)
    def test_algenta_hosts_are_recognised_regardless_of_case_port_or_path(
        self, url: str
    ) -> None:
        assert is_algenta_owned_base_url(url) is True
        assert is_algenta_owned_base_url(url.upper()) is True

    @_FAST
    @given(_SELF_HOSTED_URL)
    def test_other_hosts_are_never_treated_as_algenta_owned(self, url: str) -> None:
        assert is_algenta_owned_base_url(url) is False
        assert is_algenta_owned_base_url(url.upper()) is False

    @_FAST
    @given(
        absolute_urls(),
        st.from_regex(r"([a-z0-9._-][a-z0-9/._-]{0,19})?", fullmatch=True),
    )
    def test_join_url_path_puts_exactly_one_slash_between_base_and_path(
        self, base: str, path: str
    ) -> None:
        joined = _join_url_path(base, path)
        assert joined == f"{base}/{path}"
        assert _join_url_path(f"{base}/", path) == joined
        assert _join_url_path(base, f"/{path}") == joined


class TestPrivacyProfileEnvironment:
    @_FAST
    @given(
        st.sampled_from(_TRUE_WORDS + _FALSE_WORDS),
        st.sampled_from([str.lower, str.upper, str.title]),
        st.text(alphabet=" \t"),
        st.text(alphabet=" \t"),
    )
    def test_boolean_spellings_are_case_and_whitespace_insensitive(
        self, word: str, casing: Any, lead: str, trail: str
    ) -> None:
        assert _parse_optional_bool(f"{lead}{casing(word)}{trail}") is (word in _TRUE_WORDS)

    @_FAST
    @given(st.text().filter(lambda s: s.strip().lower() not in _TRUE_WORDS + _FALSE_WORDS))
    def test_every_other_spelling_is_rejected(self, text: str) -> None:
        with pytest.raises(ValueError, match="ALGENTA_DISABLE_CLOUD"):
            _parse_optional_bool(text)

    @_FAST
    @given(st.text(), st.sampled_from(_TRUE_WORDS), st.sampled_from(_FALSE_WORDS))
    def test_explicit_disable_flag_overrides_any_deployment_mode(
        self, mode: str, yes: str, no: str
    ) -> None:
        env = {"ALGENTA_DEPLOYMENT_MODE": mode}
        assert cloud_disabled({**env, "ALGENTA_DISABLE_CLOUD": yes}) is True
        assert cloud_disabled({**env, "ALGENTA_DISABLE_CLOUD": no}) is False

    @_FAST
    @given(
        _SELF_HOSTED_URL,
        _SELF_HOSTED_URL,
        st.sampled_from(["saas", "self_hosted", "air_gapped"]),
    )
    def test_explicit_base_url_beats_the_environment_which_beats_the_default(
        self, explicit: str, from_env: str, mode: str
    ) -> None:
        env = {"ALGENTA_BASE_URL": from_env, "ALGENTA_DEPLOYMENT_MODE": mode}
        resolved = resolve_client_base_url(explicit_base_url=explicit, component="t", env=env)
        assert resolved == normalize_base_url(explicit, component="t")
        resolved = resolve_client_base_url(explicit_base_url=None, component="t", env=env)
        assert resolved == normalize_base_url(from_env, component="t")
        assert resolve_client_base_url(explicit_base_url=None, component="t", env={}) == (
            DEFAULT_BASE_URL
        )

    @_FAST
    @given(_ALGENTA_CLOUD_URL, st.sampled_from(["self_hosted", "air_gapped"]))
    def test_private_profiles_fail_closed_on_algenta_cloud_urls(
        self, cloud_url: str, mode: str
    ) -> None:
        with pytest.raises(ValueError, match="cannot target Algenta-owned"):
            resolve_client_base_url(
                explicit_base_url=cloud_url,
                component="t",
                env={"ALGENTA_DEPLOYMENT_MODE": mode},
            )
        # The very same URL is fine for the default (saas) profile.
        resolved = resolve_client_base_url(explicit_base_url=cloud_url, component="t", env={})
        assert resolved == normalize_base_url(cloud_url, component="t")


# --- contract_fallback --------------------------------------------------------

_SECTION = st.dictionaries(st.text(max_size=5), _JSON, max_size=4)


class TestContractFallback:
    @_FAST
    @given(
        absolute_urls(host=_UNOWNED_HOST, path=st.just("")),
        st.from_regex(r"/[a-z0-9/._-]{0,20}", fullmatch=True),
        st.one_of(st.none(), st.from_regex(r"[a-z]+=[a-z0-9]+", fullmatch=True)),
    )
    def test_rebasing_keeps_path_and_query_and_is_idempotent(
        self, base: str, path: str, query: str | None
    ) -> None:
        suffix = path if query is None else f"{path}?{query}"
        cloud_endpoint = f"{DEFAULT_BASE_URL}{suffix}"
        rebased = _rebase_endpoint(base, cloud_endpoint)
        assert rebased == f"{base}{suffix}"
        # Rebasing an already-rebased endpoint onto the same base is a no-op...
        assert _rebase_endpoint(base, rebased) == rebased
        # ...and a relative suffix is its own suffix.
        assert _endpoint_suffix(suffix) == suffix
        assert _endpoint_suffix(_endpoint_suffix(cloud_endpoint)) == _endpoint_suffix(
            cloud_endpoint
        )

    @_FAST
    @given(_SECTION, _SECTION)
    def test_merge_is_a_deep_right_biased_union_that_never_aliases_its_inputs(
        self, base: dict[str, Any], override: dict[str, Any]
    ) -> None:
        base_snapshot, override_snapshot = deepcopy(base), deepcopy(override)
        merged = _merge_contract_sections(base, override)
        assert base == base_snapshot
        assert override == override_snapshot
        assert set(merged) == set(base) | set(override)
        for key, value in override.items():
            if not (isinstance(value, dict) and isinstance(base.get(key), dict)):
                assert merged[key] == value
        for key in set(base) - set(override):
            assert merged[key] == base[key]
        for key, value in merged.items():
            if isinstance(value, dict | list):
                assert value is not base.get(key)
                assert value is not override.get(key)
        assert _merge_contract_sections(base, {}) == base
        assert _merge_contract_sections(merged, override) == merged


# --- validation_error_details -------------------------------------------------

_PATH_TOKEN = st.from_regex(r"[A-Za-z0-9_.\[\]-]{1,20}", fullmatch=True)
_DETAIL = (
    st.text(
        alphabet=st.characters(blacklist_categories=("Cc", "Cs"), blacklist_characters="\r\n"),
        min_size=1,
        max_size=40,
    )
    .map(str.strip)
    .filter(bool)
)


class TestValidationErrorDetails:
    @_FAST
    @given(
        _PATH_TOKEN,
        _DETAIL,
        st.sampled_from(("", *_KNOWN_PYDANTIC_ERROR_PREFIXES)),
        st.sampled_from([": ", ":", " "]),
    )
    def test_prefixed_messages_split_into_path_and_detail(
        self, path: str, detail: str, prefix: str, separator: str
    ) -> None:
        details = build_validation_error_details(ValueError(f"{prefix}{path}{separator}{detail}"))
        assert details == {
            "cause": path,
            "validation_errors": [{"path": path, "message": detail, "type": "value_error"}],
        }

    @_FAST
    @given(st.text())
    def test_arbitrary_messages_always_yield_a_well_formed_details_dict(
        self, message: str
    ) -> None:
        details = build_validation_error_details(RuntimeError(message))
        assert isinstance(details["cause"], str)
        if "validation_errors" in details:
            (entry,) = details["validation_errors"]
            assert details["cause"] == entry["path"]
            assert entry["path"] in message
            assert entry["message"] in message
        else:
            assert details == {"cause": message}

    @settings(_FAST, max_examples=50)
    @given(
        st.from_regex(r"f_[a-z0-9_]{0,10}", fullmatch=True),
        st.from_regex(r"g_[a-z0-9_]{0,10}", fullmatch=True),
    )
    def test_pydantic_field_locations_become_dotted_paths(self, outer: str, inner: str) -> None:
        # Field names carry a prefix so they can never shadow BaseModel attributes.
        inner_model = create_model("Inner", **{inner: (int, ...)})
        outer_model = create_model("Outer", **{outer: (inner_model, ...)})
        with pytest.raises(PydanticValidationError) as excinfo:
            outer_model.model_validate({outer: {inner: "not-an-int"}})
        details = build_validation_error_details(excinfo.value)
        assert details["cause"] == f"{outer}.{inner}"
        (entry,) = details["validation_errors"]
        assert entry["path"] == f"{outer}.{inner}"
        assert entry["type"]


# --- device identity ----------------------------------------------------------

# os.environ values must be UTF-8 encodable (no lone surrogates) and NUL-free.
_ENV_SAFE_TEXT = st.text(alphabet=st.characters(codec="utf-8", exclude_characters="\x00"))


class TestDeviceIdentity:
    @_FAST
    @given(st.text())
    def test_device_id_validation_accepts_exactly_the_documented_length_range(
        self, raw: str
    ) -> None:
        stripped = raw.strip()
        if _DEVICE_ID_MIN_LENGTH <= len(stripped) <= _DEVICE_ID_MAX_LENGTH:
            assert _validate_device_id(raw, "TEST_SOURCE") == stripped
            assert _validate_device_id(stripped, "TEST_SOURCE") == stripped
        else:
            with pytest.raises(ValueError, match="TEST_SOURCE"):
                _validate_device_id(raw, "TEST_SOURCE")

    @_FAST
    @given(st.text())
    def test_derived_ids_are_deterministic_hex_prefixes_of_the_fingerprint(
        self, seed: str
    ) -> None:
        device_id = _derived_device_id_from_seed(seed)
        assert _HEX_32.match(device_id)
        assert _derived_device_id_from_seed(seed) == device_id
        fingerprint = _fingerprint_hash(seed)
        assert _HEX_64.match(fingerprint)
        assert fingerprint.startswith(device_id)

    @_FAST
    @given(
        _ENV_SAFE_TEXT.map(str.strip).filter(
            lambda s: _DEVICE_ID_MIN_LENGTH <= len(s) <= _DEVICE_ID_MAX_LENGTH
        ),
        st.text(),
        st.text(),
    )
    def test_headers_honour_explicit_device_ids_and_length_caps(
        self, device_id: str, sdk_version: str, user_agent: str
    ) -> None:
        with mock.patch.dict(os.environ, {"ALGENTA_DEVICE_ID": device_id}):
            headers = build_device_headers(sdk_version=sdk_version, user_agent=user_agent)
        assert set(headers) <= {
            DEVICE_ID_HEADER,
            HOSTNAME_HASH_HEADER,
            PLATFORM_HEADER,
            PLATFORM_VERSION_HEADER,
            SDK_VERSION_HEADER,
        }
        assert headers[DEVICE_ID_HEADER] == device_id
        assert headers[SDK_VERSION_HEADER] == sdk_version[:_SDK_VERSION_MAX_LENGTH]
        assert len(headers.get(PLATFORM_HEADER, "")) <= _PLATFORM_MAX_LENGTH
        assert len(headers.get(PLATFORM_VERSION_HEADER, "")) <= _PLATFORM_VERSION_MAX_LENGTH
        assert _HEX_64.match(headers[HOSTNAME_HASH_HEADER])


class TestDeviceBindingStore:
    _OPAQUE = st.text(min_size=1).map(str.strip).filter(bool)

    @_FAST
    @given(_SELF_HOSTED_URL, _OPAQUE, _OPAQUE)
    def test_store_keys_are_hex_and_ignore_trailing_slashes(
        self, base_url: str, api_key: str, device_id: str
    ) -> None:
        key = _binding_store_key(base_url, api_key, device_id)
        assert _HEX_64.match(key)
        assert _binding_store_key(f"{base_url}/", api_key, device_id) == key
        assert _binding_store_key(f"{base_url}///", api_key, device_id) == key

    @_FAST
    @given(_SELF_HOSTED_URL, _OPAQUE, _OPAQUE, st.text(min_size=1).filter(str.strip))
    def test_tokens_round_trip_through_the_on_disk_store(
        self, base_url: str, api_key: str, device_id: str, token: str
    ) -> None:
        # The autouse conftest fixture points ALGENTA_RUNTIME_DIR at a tmp dir.
        identity = {"base_url": base_url, "api_key": api_key, "device_id": device_id}
        store_device_binding_token(binding_token=token, **identity)
        device_binding._MEMORY_STORE.clear()  # force the read to come from disk
        assert load_device_binding_token(**identity) == token.strip()
        assert load_device_binding_token(**{**identity, "base_url": f"{base_url}/"}) == (
            token.strip()
        )


# --- transport_response -------------------------------------------------------

_SUCCESS_STATUSES = (200, 201, 202, 204)
_ERROR_CLASS_BY_STATUS = {
    401: AuthenticationError,
    404: NotFoundError,
    422: ValidationError,
    429: RateLimitError,
}
# Header values must be ASCII for httpx.
_REQUEST_ID = st.from_regex(r"[A-Za-z0-9-]{1,32}", fullmatch=True)
# The API's structured error envelope. (A body whose `error` is not an object is
# out of contract and not generated here.)
_ERROR_ENVELOPE = st.fixed_dictionaries(
    {
        "error": st.fixed_dictionaries(
            {}, optional={"message": st.text(), "code": _IDENTIFIER, "details": _JSON}
        )
    },
    optional={"request_id": _REQUEST_ID},
)


def _expected_error_class(status: int) -> type[DecisionEngineError]:
    if status in _ERROR_CLASS_BY_STATUS:
        return _ERROR_CLASS_BY_STATUS[status]
    return ServerError if status >= 500 else DecisionEngineError


class TestHandleResponse:
    @_FAST
    @given(
        st.integers(min_value=100, max_value=599),
        _ERROR_ENVELOPE,
        st.one_of(st.none(), _REQUEST_ID),
        st.one_of(st.none(), st.integers(min_value=0, max_value=10**6)),
    )
    def test_every_status_maps_to_exactly_one_outcome(
        self,
        status: int,
        body: dict[str, Any],
        header_request_id: str | None,
        retry_after: int | None,
    ) -> None:
        headers: dict[str, str] = {}
        if header_request_id is not None:
            headers["X-Request-Id"] = header_request_id
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        response = httpx.Response(status, json=body, headers=headers)

        if status in _SUCCESS_STATUSES:
            assert handle_response(response, auth_message="auth") == body
            return

        with pytest.raises(DecisionEngineError) as excinfo:
            handle_response(response, auth_message="auth")
        exc = excinfo.value
        assert type(exc) is _expected_error_class(status)
        assert exc.status_code == status
        assert exc.response_body == body
        # request_id precedence: body first, then the X-Request-Id header.
        assert exc.request_id == (body.get("request_id") or header_request_id)
        assert exc.error_code == body["error"].get("code", "unknown_error")
        if type(exc) is DecisionEngineError:
            # The catch-all branch (1xx/3xx/4xx without a dedicated class)
            # reports the status and never the body's message.
            assert str(exc) == f"Unexpected status {status}"
        elif "message" in body["error"]:
            assert str(exc) == body["error"]["message"]
        else:
            assert str(exc)
        if isinstance(exc, RateLimitError):
            expected_retry = DEFAULT_RETRY_AFTER_SECONDS if retry_after is None else retry_after
            assert exc.retry_after == expected_retry

    @_FAST
    @given(
        st.integers(min_value=100, max_value=599).filter(lambda s: s not in _SUCCESS_STATUSES),
        st.text(),
    )
    def test_non_json_error_bodies_still_raise_the_typed_error(
        self, status: int, text: str
    ) -> None:
        response = httpx.Response(status, content=f"not json: {text}".encode())
        with pytest.raises(DecisionEngineError) as excinfo:
            handle_response(response, auth_message="auth")
        assert type(excinfo.value) is _expected_error_class(status)
        assert excinfo.value.status_code == status
        assert excinfo.value.error_code == "unknown_error"
        assert excinfo.value.response_body == {}

    @_FAST
    @given(_JSON)
    def test_validation_errors_is_always_a_list_of_objects(self, details: Any) -> None:
        exc = DecisionEngineError("m", response_body={"error": {"details": details}})
        entries = exc.validation_errors
        assert isinstance(entries, list)
        assert all(isinstance(entry, dict) for entry in entries)
        if isinstance(details, list):
            assert entries == [entry for entry in details if isinstance(entry, dict)]
        elif isinstance(details, dict) and isinstance(details.get("validation_errors"), list):
            assert entries == [
                entry for entry in details["validation_errors"] if isinstance(entry, dict)
            ]
        else:
            assert entries == []
        assert exc.field_errors == entries
