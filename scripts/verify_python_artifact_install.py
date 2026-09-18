"""Verify the Python SDK installs + imports from the BUILT ARTIFACT (wheel), not just source.

The release workflow already builds + `twine check`s; this is the stronger "a user can actually
`pip install` it" proof: build the wheel + sdist, install the wheel into a FRESH venv (no repo on
sys.path), and run an import smoke in that venv. Catches the classic "works from source but the
wheel is missing modules / has bad metadata" failure.

Run locally or in CI:  python scripts/verify_python_artifact_install.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility; `build` installs tomli.
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = _ROOT / "packages" / "python-sdk"


def _project_version() -> str:
    pyproject = _PKG_DIR / "pyproject.toml"
    return tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]


def _run(cmd: list[str], **kw) -> None:
    subprocess.run(cmd, check=True, **kw)


def main() -> int:
    version = _project_version()
    smoke = (
        "import decision_engine as m; "
        "from decision_engine import DecisionEngineClient, AlgentaClient; "
        f"assert m.__version__ == {version!r}, m.__version__; "
        "assert DecisionEngineClient and AlgentaClient; "
        "print('algenta-sdk (python)', m.__version__, 'OK')"
    )
    with tempfile.TemporaryDirectory(prefix="artifact-python-sdk-") as tmp:
        dist = Path(tmp) / "dist"
        _run([sys.executable, "-m", "build", "--outdir", str(dist), str(_PKG_DIR)], cwd=tmp)
        wheels = list(dist.glob("*.whl"))
        sdists = list(dist.glob("*.tar.gz"))
        assert wheels, "python-sdk: no wheel built"
        assert sdists, "python-sdk: no sdist built"

        env_dir = Path(tmp) / "venv"
        venv.create(env_dir, with_pip=True)
        py = env_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
        _run([str(py), "-m", "pip", "install", "--quiet", str(wheels[0])])
        # Import smoke from a cwd with no repo source, so it loads the INSTALLED package.
        _run([str(py), "-c", smoke], cwd=tmp)
        print(f"[ok] python-sdk: built {wheels[0].name} + {sdists[0].name}, fresh-venv install + import OK")

    print("\nPython SDK artifact installs + imports from the wheel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
