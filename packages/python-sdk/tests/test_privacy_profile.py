"""Tests for the privacy-profile base-URL resolution (fail-closed rules)."""

from __future__ import annotations

import pytest

from decision_engine import AlgentaClient
from decision_engine.privacy_profile import (
    api_key_help_text,
    cloud_disabled,
    is_algenta_owned_base_url,
    normalize_base_url,
    private_profile_enabled,
    resolve_api_keys_url,
    resolve_client_base_url,
    resolve_console_base_url,
)

from .conftest import TEST_API_KEY


class TestCloudDisabled:
    def test_saas_is_the_default_mode(self) -> None:
        assert cloud_disabled({}) is False
        assert private_profile_enabled({}) is False

    @pytest.mark.parametrize("mode", ["self_hosted", "air_gapped", "SELF_HOSTED"])
    def test_private_deployment_modes_disable_cloud(self, mode: str) -> None:
        env = {"ALGENTA_DEPLOYMENT_MODE": mode}
        assert cloud_disabled(env) is True
        assert private_profile_enabled(env) is True

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
    def test_explicit_disable_flag_accepts_boolean_spellings(self, value: str) -> None:
        assert cloud_disabled({"ALGENTA_DISABLE_CLOUD": value}) is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off"])
    def test_explicit_disable_flag_can_reenable_cloud_in_private_mode(
        self, value: str
    ) -> None:
        env = {"ALGENTA_DEPLOYMENT_MODE": "self_hosted", "ALGENTA_DISABLE_CLOUD": value}
        assert cloud_disabled(env) is False
        # The private *profile* still applies for console/help surfaces.
        assert private_profile_enabled(env) is True

    def test_invalid_disable_flag_value_raises(self) -> None:
        with pytest.raises(ValueError, match="ALGENTA_DISABLE_CLOUD"):
            cloud_disabled({"ALGENTA_DISABLE_CLOUD": "maybe"})


class TestIsAlgentaOwnedBaseUrl:
    @pytest.mark.parametrize(
        "base_url",
        [
            "https://api.algenta.ai",
            "https://algenta.ai",
            "https://staging.api.algenta.ai",
            "https://API.ALGENTA.AI",
            "https://api.algenta.io",
        ],
    )
    def test_algenta_hosts_and_suffixes_match(self, base_url: str) -> None:
        assert is_algenta_owned_base_url(base_url) is True

    @pytest.mark.parametrize(
        "base_url",
        [
            "https://engine.example.com",
            "https://algenta.ai.evil.example.com",
            "https://notalgenta.ai",
            "http://localhost:8080",
        ],
    )
    def test_third_party_hosts_do_not_match(self, base_url: str) -> None:
        assert is_algenta_owned_base_url(base_url) is False


class TestNormalizeBaseUrl:
    def test_strips_whitespace_and_trailing_slashes(self) -> None:
        assert normalize_base_url("  https://engine.example.com/  ", component="Test") == (
            "https://engine.example.com"
        )

    @pytest.mark.parametrize("bad", ["engine.example.com", "/relative/path", ""])
    def test_rejects_non_absolute_urls(self, bad: str) -> None:
        with pytest.raises(ValueError, match="absolute URL"):
            normalize_base_url(bad, component="Test")


class TestResolveClientBaseUrl:
    def test_explicit_base_url_wins_over_everything(self) -> None:
        env = {"ALGENTA_BASE_URL": "https://env.example.com"}
        resolved = resolve_client_base_url(
            explicit_base_url="https://explicit.example.com", component="Test", env=env
        )
        assert resolved == "https://explicit.example.com"

    def test_environment_resolution_order(self) -> None:
        env = {
            "ALGENTA_BASE_URL": "https://primary.example.com",
            "DE_BASE_URL": "https://legacy.example.com",
            "ALGENTA_API_URL": "https://oldest.example.com",
        }
        resolved = resolve_client_base_url(
            explicit_base_url=None, component="Test", env=env
        )
        assert resolved == "https://primary.example.com"

    def test_legacy_env_vars_are_still_read(self) -> None:
        env = {"ALGENTA_API_URL": "https://oldest.example.com"}
        resolved = resolve_client_base_url(
            explicit_base_url=None, component="Test", env=env
        )
        assert resolved == "https://oldest.example.com"

    def test_defaults_to_the_algenta_cloud(self) -> None:
        resolved = resolve_client_base_url(explicit_base_url=None, component="Test", env={})
        assert resolved == "https://api.algenta.ai"

    @pytest.mark.parametrize("mode", ["self_hosted", "air_gapped"])
    def test_private_profiles_fail_closed_on_algenta_cloud_urls(self, mode: str) -> None:
        env = {"ALGENTA_DEPLOYMENT_MODE": mode}
        with pytest.raises(ValueError, match="cannot target Algenta-owned cloud URLs"):
            resolve_client_base_url(
                explicit_base_url="https://api.algenta.ai", component="Test", env=env
            )

    @pytest.mark.parametrize("mode", ["self_hosted", "air_gapped"])
    def test_private_profiles_accept_self_hosted_urls(self, mode: str) -> None:
        env = {"ALGENTA_DEPLOYMENT_MODE": mode}
        resolved = resolve_client_base_url(
            explicit_base_url="https://engine.internal:8443", component="Test", env=env
        )
        assert resolved == "https://engine.internal:8443"

    def test_private_profile_without_any_base_url_fails_closed(self) -> None:
        env = {"ALGENTA_DEPLOYMENT_MODE": "self_hosted"}
        # The default is the Algenta cloud, so omitting base_url is rejected
        # rather than silently targeting cloud from a private profile.
        with pytest.raises(ValueError, match="cannot target Algenta-owned cloud URLs"):
            resolve_client_base_url(explicit_base_url=None, component="Test", env=env)


class TestConsoleResolution:
    def test_saas_defaults_to_the_hosted_console(self) -> None:
        assert resolve_console_base_url(component="Test", env={}) == "https://app.algenta.ai"
        assert (
            resolve_api_keys_url(component="Test", env={})
            == "https://app.algenta.ai/dashboard/api-keys"
        )

    def test_console_env_override_wins(self) -> None:
        env = {"ALGENTA_APP_BASE_URL": "https://console.example.com"}
        assert (
            resolve_console_base_url(component="Test", env=env)
            == "https://console.example.com"
        )

    def test_private_profile_uses_the_api_base_url_as_console_fallback(self) -> None:
        env = {
            "ALGENTA_DEPLOYMENT_MODE": "self_hosted",
            "ALGENTA_BASE_URL": "https://engine.internal:8443",
        }
        assert (
            resolve_console_base_url(component="Test", env=env)
            == "https://engine.internal:8443"
        )

    def test_private_profile_without_console_or_base_url_fails_closed(self) -> None:
        env = {"ALGENTA_DEPLOYMENT_MODE": "air_gapped"}
        with pytest.raises(ValueError, match="require an explicit self-hosted"):
            resolve_console_base_url(component="Test", env=env)

    def test_private_profile_rejects_algenta_owned_console_override(self) -> None:
        env = {
            "ALGENTA_DEPLOYMENT_MODE": "self_hosted",
            "ALGENTA_APP_BASE_URL": "https://app.algenta.ai",
        }
        with pytest.raises(ValueError, match="cannot target Algenta-owned cloud URLs"):
            resolve_console_base_url(component="Test", env=env)

    def test_api_key_help_text_points_at_the_console_in_saas(self) -> None:
        text = api_key_help_text(component="Test", env={})
        assert text == "Get a key at: https://app.algenta.ai/dashboard/api-keys"

    def test_api_key_help_text_points_at_the_self_hosted_surface(self) -> None:
        env = {
            "ALGENTA_DEPLOYMENT_MODE": "self_hosted",
            "ALGENTA_BASE_URL": "https://engine.internal:8443",
        }
        text = api_key_help_text(component="Test", env=env)
        assert text == (
            "Create a key from your self-hosted admin surface or API base URL: "
            "https://engine.internal:8443"
        )


class TestClientConstructionFailClosed:
    """End-to-end: the client must not silently target cloud in private mode."""

    def test_self_hosted_mode_rejects_the_default_cloud_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALGENTA_DEPLOYMENT_MODE", "self_hosted")
        with pytest.raises(ValueError, match="cannot target Algenta-owned cloud URLs"):
            AlgentaClient(api_key=TEST_API_KEY)

    def test_air_gapped_mode_rejects_an_explicit_cloud_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALGENTA_DEPLOYMENT_MODE", "air_gapped")
        with pytest.raises(ValueError, match="cannot target Algenta-owned cloud URLs"):
            AlgentaClient(api_key=TEST_API_KEY, base_url="https://api.algenta.ai")

    def test_self_hosted_mode_accepts_a_self_hosted_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALGENTA_DEPLOYMENT_MODE", "self_hosted")
        client = AlgentaClient(
            api_key=TEST_API_KEY, base_url="https://engine.internal:8443"
        )
        assert client._base_url == "https://engine.internal:8443"
