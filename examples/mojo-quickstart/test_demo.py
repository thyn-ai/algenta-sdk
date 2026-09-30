#!/usr/bin/env python3
"""Expected-output test for the Algenta × Mojo quickstart.

Runs the compiled demo binary and validates that every protocol step
(handshake, ping, single library_execute, batch_execute, shutdown) printed
its deterministic, expected output. This test is intentionally stdlib-only
and requires no network access.
"""

from __future__ import annotations

import re
import subprocess
import sys

DEMO_BINARY = "./algenta-mojo-demo"

EXPECTED_PATTERNS = [
    r"< handshake: \{\"status\":\"ready\"\}",
    r"> ping: \{\"type\":\"ping\"\}",
    r"< \{\"status\":\"ok\"\}",
    r"activations\.gelu\(1\.0\)\s*=\s*0\.841191990607477",
    r"batch_execute\(2 requests\)\s+ok=2\s+failed=0",
    r"ok: handshake, ping, library_execute, batch_execute and shutdown all succeeded",
]


def main() -> int:
    result = subprocess.run(
        [DEMO_BINARY],
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    if result.returncode != 0:
        print("FAIL: demo exited with code", result.returncode)
        print(output)
        return 1

    missing: list[str] = []
    for pattern in EXPECTED_PATTERNS:
        if not re.search(pattern, output):
            missing.append(pattern)

    if missing:
        print("FAIL: output missing expected patterns:")
        for pattern in missing:
            print("  -", pattern)
        print("--- captured output ---")
        print(output)
        return 1

    if "error:" in output.lower():
        print("FAIL: output contains an error diagnostic")
        print(output)
        return 1

    print("PASS: quickstart produced all expected deterministic outputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
