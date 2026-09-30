# SPDX-License-Identifier: Apache-2.0

"""Verify that docs/configuration.md documents every public client option."""

from __future__ import annotations

from pathlib import Path

import pytest


def _repo_root() -> Path:
    """Return the repository root from the test file location."""
    # This test lives at packages/python-sdk/tests/test_docs_configuration.py.
    return Path(__file__).resolve().parents[3]


def _docs_file() -> Path:
    return _repo_root() / "docs" / "configuration.md"


@pytest.fixture
def configuration_doc() -> str:
    path = _docs_file()
    if not path.exists():
        pytest.fail(f"Missing documentation file: {path}")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "required_section",
    [
        "## Python client",
        "### Constructor options",
        "### Environment variables",
        "### Defaults",
        "## TypeScript client",
        "## Cross-reference",
    ],
)
def test_configuration_doc_has_required_sections(
    configuration_doc: str,
    required_section: str,
) -> None:
    assert required_section in configuration_doc, f"Missing section: {required_section}"


@pytest.mark.parametrize(
    "required_token",
    [
        # Python public constructor options
        "`api_key`",
        "`base_url`",
        "`timeout`",
        "`max_retries`",
        "`AlgentaClient`",
        "`AsyncAlgentaClient`",
        # Python defaults
        "`120.0`",
        "`3`",
        "`DEFAULT_TIMEOUT`",
        "`DEFAULT_MAX_RETRIES`",
        # TypeScript public constructor options
        "`apiKey`",
        "`baseUrl`",
        "`maxRetries`",
        "`defaultHeaders`",
        "`DecisionEngineClientConfig`",
        # TypeScript defaults
        "`120_000`",
        # Authentication env vars
        "`ALGENTA_API_KEY`",
        "`DE_API_KEY`",
        # Base URL env vars
        "`ALGENTA_BASE_URL`",
        "`DE_BASE_URL`",
        "`ALGENTA_API_URL`",
        # Default hosted URL
        "`https://api.algenta.ai`",
        # Deployment profile env vars
        "`ALGENTA_DEPLOYMENT_MODE`",
        "`ALGENTA_DISABLE_CLOUD`",
        # Console URL env vars
        "`ALGENTA_APP_BASE_URL`",
        "`APP_BASE_URL`",
        "`DE_APP_BASE_URL`",
        # Device / runtime env vars
        "`ALGENTA_DEVICE_ID`",
        "`DE_DEVICE_ID`",
        "`ALGENTA_RUNTIME_DIR`",
        # Device headers
        "`X-Algenta-Device-Id`",
        "`X-Algenta-SDK-Version`",
        # Retry behavior
        "`429`",
        "`5xx`",
        # Proxy guidance
        "`HTTP_PROXY`",
        "`HTTPS_PROXY`",
    ],
)
def test_configuration_doc_covers_public_options(
    configuration_doc: str,
    required_token: str,
) -> None:
    assert required_token in configuration_doc, f"Missing option: {required_token}"


def test_configuration_doc_is_valid_markdown(configuration_doc: str) -> None:
    """Smoke-check that the file renders as a balanced Markdown document."""
    # No unclosed code fences.
    fence_count = configuration_doc.count("```")
    assert fence_count % 2 == 0, "Unclosed fenced code block in configuration.md"

    # All tables have a header separator row (| --- |).
    for line_number, line in enumerate(configuration_doc.splitlines(), start=1):
        if line.startswith("| ") and "---" not in line:
            # Every table row after the header must contain a cell delimiter.
            assert " | " in line, f"Malformed table row at line {line_number}: {line}"
