"""Tests that docs/errors.md documents every exported Python exception.

These tests are documentation guards: if a new exception is exported from the
public API but is not mentioned in the shared error reference, CI fails.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import decision_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_FILE = REPO_ROOT / "docs" / "errors.md"
PYTHON_README = REPO_ROOT / "packages" / "python-sdk" / "README.md"
TS_README = REPO_ROOT / "packages" / "ts-sdk" / "README.md"


def _exported_exception_names() -> list[str]:
    return sorted(
        name
        for name in decision_engine.__all__
        if inspect.isclass(getattr(decision_engine, name))
        and issubclass(getattr(decision_engine, name), Exception)
    )


def test_docs_errors_exists_and_is_linked_from_both_readmes() -> None:
    assert DOCS_FILE.exists(), f"{DOCS_FILE} must exist"
    docs_content = DOCS_FILE.read_text(encoding="utf-8")
    assert docs_content.strip(), f"{DOCS_FILE} must not be empty"

    python_readme = PYTHON_README.read_text(encoding="utf-8")
    ts_readme = TS_README.read_text(encoding="utf-8")
    link = "docs/errors.md"
    assert link in python_readme, "Python README must link to docs/errors.md"
    assert link in ts_readme, "TypeScript README must link to docs/errors.md"


def test_every_exported_python_exception_is_documented() -> None:
    docs_content = DOCS_FILE.read_text(encoding="utf-8")
    missing = [name for name in _exported_exception_names() if name not in docs_content]
    assert not missing, f"docs/errors.md must document these exported exceptions: {missing}"
