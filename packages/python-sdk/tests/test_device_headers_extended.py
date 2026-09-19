"""Tests for the machine-identity probes behind the device headers.

``test_device_headers.py`` covers the header contract under the stubbed machine
seed. This module reaches the platform probes themselves: the per-OS readers
(``ioreg`` on macOS, ``/etc/machine-id`` on Linux, the registry on Windows),
the install-id fallback file, the hostname fingerprint seed, and the header
branches that depend on ``platform``. Every probe is driven through
monkeypatched ``platform``/``shutil``/``subprocess``/``Path`` calls, so no test
touches the real machine.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from decision_engine import device_headers
from decision_engine.device_headers import (
    DEVICE_ID_HEADER,
    HOSTNAME_HASH_HEADER,
    PLATFORM_HEADER,
    PLATFORM_VERSION_HEADER,
    _derived_device_id_from_seed,
    _fingerprint_hash,
    build_device_headers,
)

from .conftest import TEST_MACHINE_SEED

# Captured at import time, before the autouse fixture stubs the probe.
_REAL_RAW_MACHINE_ID = device_headers._raw_machine_id

_IOREG_OUTPUT = b"""+-o MacBook  <class IOPlatformExpertDevice>
    {
      "IOPlatformSerialNumber" = "C02XYZ"
      "IOPlatformUUID" = "7E1C4A9D-1B2C-4D3E-8F90-ABCDEF123456"
    }
"""


class TestRuntimeDir:
    def test_honours_the_configured_runtime_dir(self, isolated_environment: Path) -> None:
        assert device_headers._runtime_dir() == isolated_environment
        assert device_headers._install_id_file() == isolated_environment / "install_id"

    def test_defaults_under_the_home_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALGENTA_RUNTIME_DIR", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/ada")))

        assert device_headers._runtime_dir() == Path("/home/ada/.algenta/runtime")


class TestInstallId:
    def test_creates_a_uuid_file_and_reuses_it(self, isolated_environment: Path) -> None:
        first = device_headers._get_or_create_install_id()

        assert uuid.UUID(first)
        assert (isolated_environment / "install_id").read_text() == first
        assert device_headers._get_or_create_install_id() == first

    def test_a_blank_file_is_replaced_with_a_fresh_id(self, isolated_environment: Path) -> None:
        isolated_environment.mkdir(parents=True)
        (isolated_environment / "install_id").write_text("  \n")

        install_id = device_headers._get_or_create_install_id()

        assert uuid.UUID(install_id)
        assert (isolated_environment / "install_id").read_text() == install_id


class TestMacosProbe:
    def test_returns_none_without_ioreg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(device_headers.shutil, "which", lambda name: None)

        assert device_headers._read_macos_machine_id() is None

    def test_parses_the_platform_uuid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_check_output(args: list[str], **kwargs: object) -> bytes:
            calls.append(args)
            return _IOREG_OUTPUT

        monkeypatch.setattr(device_headers.shutil, "which", lambda name: "/usr/sbin/ioreg")
        monkeypatch.setattr(device_headers.subprocess, "check_output", fake_check_output)

        assert device_headers._read_macos_machine_id() == "7E1C4A9D-1B2C-4D3E-8F90-ABCDEF123456"
        assert calls == [["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]]

    def test_returns_none_when_the_uuid_line_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(device_headers.shutil, "which", lambda name: "/usr/sbin/ioreg")
        monkeypatch.setattr(
            device_headers.subprocess,
            "check_output",
            lambda *a, **k: b'"IOPlatformSerialNumber" = "X"\n',
        )

        assert device_headers._read_macos_machine_id() is None

    def test_returns_none_when_ioreg_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail(*args: object, **kwargs: object) -> bytes:
            raise subprocess.CalledProcessError(1, "ioreg")

        monkeypatch.setattr(device_headers.shutil, "which", lambda name: "/usr/sbin/ioreg")
        monkeypatch.setattr(device_headers.subprocess, "check_output", fail)

        assert device_headers._read_macos_machine_id() is None


class TestLinuxProbe:
    @staticmethod
    def _fake_path(contents: dict[str, str | None]) -> type:
        class FakePath:
            def __init__(self, path: str) -> None:
                self._path = path

            def read_text(self) -> str:
                value = contents.get(self._path)
                if value is None:
                    raise OSError(f"{self._path} missing")
                return value

        return FakePath

    def test_prefers_etc_machine_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            device_headers,
            "Path",
            self._fake_path({"/etc/machine-id": " etc-id \n", "/var/lib/dbus/machine-id": "dbus"}),
        )

        assert device_headers._read_linux_machine_id() == "etc-id"

    def test_falls_back_to_the_dbus_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            device_headers,
            "Path",
            self._fake_path({"/etc/machine-id": None, "/var/lib/dbus/machine-id": "dbus-id\n"}),
        )

        assert device_headers._read_linux_machine_id() == "dbus-id"

    def test_skips_an_empty_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            device_headers,
            "Path",
            self._fake_path({"/etc/machine-id": "\n", "/var/lib/dbus/machine-id": "dbus-id"}),
        )

        assert device_headers._read_linux_machine_id() == "dbus-id"

    def test_returns_none_when_neither_file_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(device_headers, "Path", self._fake_path({}))

        assert device_headers._read_linux_machine_id() is None


class TestWindowsProbe:
    def test_reads_the_machine_guid_from_the_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[tuple[object, str]] = []
        winreg = ModuleType("winreg")
        winreg.HKEY_LOCAL_MACHINE = "HKLM"
        winreg.OpenKey = lambda root, path: opened.append((root, path)) or SimpleNamespace()
        winreg.QueryValueEx = lambda key, name: ("machine-guid-1", 1)
        monkeypatch.setitem(sys.modules, "winreg", winreg)

        assert device_headers._read_windows_machine_id() == "machine-guid-1"
        assert opened == [("HKLM", r"SOFTWARE\Microsoft\Cryptography")]

    def test_returns_none_when_the_registry_is_unreadable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        winreg = ModuleType("winreg")
        winreg.HKEY_LOCAL_MACHINE = "HKLM"

        def open_key(root: object, path: str) -> object:
            raise OSError("access denied")

        winreg.OpenKey = open_key
        monkeypatch.setitem(sys.modules, "winreg", winreg)

        assert device_headers._read_windows_machine_id() is None

    def test_returns_none_when_winreg_cannot_be_imported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "winreg", None)

        assert device_headers._read_windows_machine_id() is None


class TestRawMachineId:
    @pytest.mark.parametrize(
        ("system", "reader"),
        [
            ("Darwin", "_read_macos_machine_id"),
            ("Linux", "_read_linux_machine_id"),
            ("Windows", "_read_windows_machine_id"),
        ],
    )
    def test_dispatches_on_the_platform(
        self, monkeypatch: pytest.MonkeyPatch, system: str, reader: str
    ) -> None:
        monkeypatch.setattr(device_headers.platform, "system", lambda: system)
        for name in (
            "_read_macos_machine_id",
            "_read_linux_machine_id",
            "_read_windows_machine_id",
        ):
            monkeypatch.setattr(
                device_headers, name, (lambda: f"{system}-id") if name == reader else (lambda: None)
            )

        assert _REAL_RAW_MACHINE_ID() == f"{system}-id"

    def test_falls_back_to_the_install_id_when_the_probe_is_empty(
        self, monkeypatch: pytest.MonkeyPatch, isolated_environment: Path
    ) -> None:
        monkeypatch.setattr(device_headers.platform, "system", lambda: "Linux")
        monkeypatch.setattr(device_headers, "_read_linux_machine_id", lambda: None)

        machine_id = _REAL_RAW_MACHINE_ID()

        assert machine_id == (isolated_environment / "install_id").read_text()

    def test_unknown_platforms_use_the_install_id(
        self, monkeypatch: pytest.MonkeyPatch, isolated_environment: Path
    ) -> None:
        monkeypatch.setattr(device_headers.platform, "system", lambda: "Plan9")

        assert _REAL_RAW_MACHINE_ID() == (isolated_environment / "install_id").read_text()

    def test_derived_id_hashes_the_probe_result(self) -> None:
        assert device_headers._derived_device_id() == _derived_device_id_from_seed(
            TEST_MACHINE_SEED
        )


class TestFingerprintSeed:
    def test_prefers_the_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(device_headers.platform, "node", lambda: " workstation ")

        assert device_headers._fingerprint_seed("dev", "machine") == "workstation"

    def test_falls_back_to_the_machine_id_then_the_device_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(device_headers.platform, "node", lambda: "")

        assert device_headers._fingerprint_seed("dev", "machine") == "machine"
        assert device_headers._fingerprint_seed("dev", "") == "dev"


class TestHeaderBranches:
    def test_hostname_hash_is_the_fingerprint_of_the_node_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(device_headers.platform, "node", lambda: "workstation")

        headers = build_device_headers(sdk_version="v", user_agent="ua")

        assert headers[HOSTNAME_HASH_HEADER] == _fingerprint_hash("workstation")

    def test_platform_headers_are_omitted_when_platform_reports_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(device_headers.platform, "system", lambda: "")
        monkeypatch.setattr(device_headers.platform, "release", lambda: "")

        headers = build_device_headers(sdk_version="v", user_agent="ua")

        assert PLATFORM_HEADER not in headers
        assert PLATFORM_VERSION_HEADER not in headers
        assert headers[DEVICE_ID_HEADER] == _derived_device_id_from_seed(TEST_MACHINE_SEED)

    def test_platform_values_are_truncated_to_their_budgets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(device_headers.platform, "system", lambda: "S" * 80)
        monkeypatch.setattr(device_headers.platform, "release", lambda: "R" * 80)

        headers = build_device_headers(sdk_version="v", user_agent="ua")

        assert headers[PLATFORM_HEADER] == "S" * 50
        assert headers[PLATFORM_VERSION_HEADER] == "R" * 50

    def test_an_explicit_device_id_still_fingerprints_the_machine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With an explicit id the probe is skipped for the id but still seeds the hostname hash."""
        monkeypatch.setenv("ALGENTA_DEVICE_ID", "explicit-device-id-1")
        monkeypatch.setattr(device_headers.platform, "node", lambda: "")

        headers = build_device_headers(sdk_version="v", user_agent="ua")

        assert headers[DEVICE_ID_HEADER] == "explicit-device-id-1"
        assert headers[HOSTNAME_HASH_HEADER] == _fingerprint_hash(TEST_MACHINE_SEED)

    def test_explicit_device_id_is_trimmed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALGENTA_DEVICE_ID", "  explicit-device-id-1  ")

        assert device_headers._explicit_device_id() == "explicit-device-id-1"

    def test_no_explicit_device_id_yields_none(self) -> None:
        assert device_headers._explicit_device_id() is None
