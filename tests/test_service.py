"""Tests for animus.service — the cross-platform daemon installer."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from animus import service as svc


def _fake_completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# ── ServiceInfo ───────────────────────────────────────────────────────────


def test_service_info_to_dict_round_trip():
    info = svc.ServiceInfo("windows", True, True, "running fine")
    d = info.to_dict()
    assert d == {
        "platform": "windows",
        "installed": True,
        "running": True,
        "detail": "running fine",
    }


# ── detect_platform ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "system,expected_prefix",
    [("Windows", "windows"), ("Darwin", "darwin"), ("Linux", "linux")],
)
def test_detect_platform_known(monkeypatch, system, expected_prefix):
    monkeypatch.setattr(svc.platform, "system", lambda: system)
    if system == "Linux":
        monkeypatch.setattr(svc.shutil, "which", lambda _: "/usr/bin/systemctl")
    assert svc.detect_platform().startswith(expected_prefix)


def test_detect_platform_linux_without_systemctl(monkeypatch):
    monkeypatch.setattr(svc.platform, "system", lambda: "Linux")
    monkeypatch.setattr(svc.shutil, "which", lambda _: None)
    assert svc.detect_platform() == "unsupported"


def test_detect_platform_unknown(monkeypatch):
    monkeypatch.setattr(svc.platform, "system", lambda: "OS/2")
    assert svc.detect_platform() == "unsupported"


# ── default_log_path / default_animus_exe ─────────────────────────────────


def test_default_log_path_lives_under_data_dir(tmp_path):
    assert svc.default_log_path(tmp_path) == tmp_path / "daemon.log"


def test_default_animus_exe_returns_a_path():
    p = svc.default_animus_exe()
    assert isinstance(p, Path)


# ── Public dispatch falls back gracefully on unsupported OS ───────────────


def test_install_unsupported(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "detect_platform", lambda: "unsupported")
    info = svc.install(tmp_path / "animus", tmp_path / "log.txt")
    assert info.installed is False
    assert info.platform == "unsupported"


def test_uninstall_unsupported(monkeypatch):
    monkeypatch.setattr(svc, "detect_platform", lambda: "unsupported")
    assert svc.uninstall().installed is False


def test_status_unsupported(monkeypatch):
    monkeypatch.setattr(svc, "detect_platform", lambda: "unsupported")
    assert svc.status().installed is False


def test_start_stop_unsupported(monkeypatch):
    monkeypatch.setattr(svc, "detect_platform", lambda: "unsupported")
    assert svc.start().installed is False
    assert svc.stop().installed is False


# ── systemd backend ───────────────────────────────────────────────────────


def test_systemd_install_writes_unit_and_enables(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(svc, "detect_platform", lambda: "linux-systemd")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _fake_completed(stdout="active", returncode=0)

    monkeypatch.setattr(svc.subprocess, "run", fake_run)

    info = svc.install(tmp_path / "animus", tmp_path / "log.txt")

    unit_path = home / ".config" / "systemd" / "user" / svc.SYSTEMD_UNIT
    assert unit_path.exists()
    body = unit_path.read_text()
    assert "ExecStart=" in body
    assert "daemon --log-file" in body
    # daemon-reload + enable + at least is-active was invoked
    assert any("daemon-reload" in c for c in calls)
    assert any("enable" in c for c in calls)
    assert info.platform == "linux-systemd"
    assert info.installed is True


def test_systemd_uninstall_removes_unit(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(svc, "detect_platform", lambda: "linux-systemd")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    unit = home / ".config" / "systemd" / "user" / svc.SYSTEMD_UNIT
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[Unit]\n")

    monkeypatch.setattr(svc.subprocess, "run", lambda *a, **kw: _fake_completed())

    info = svc.uninstall()
    assert not unit.exists()
    assert info.installed is False


def test_systemd_status_reports_active(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(svc, "detect_platform", lambda: "linux-systemd")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    unit = home / ".config" / "systemd" / "user" / svc.SYSTEMD_UNIT
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text("[Unit]\n")

    monkeypatch.setattr(
        svc.subprocess, "run",
        lambda *a, **kw: _fake_completed(stdout="active\n"),
    )

    info = svc.status()
    assert info.installed is True
    assert info.running is True


def test_systemd_status_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "detect_platform", lambda: "linux-systemd")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    info = svc.status()
    assert info.installed is False


# ── windows backend (mocked PowerShell) ───────────────────────────────────


def test_windows_install_invokes_powershell(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "detect_platform", lambda: "windows")
    captured = {}

    def fake_ps(script, capture=True):
        captured.setdefault("scripts", []).append(script)
        # First call (install) → no error; status call returns Running
        if "Get-ScheduledTask" in script:
            return _fake_completed(stdout="Running|2026-05-04|0\n")
        return _fake_completed()

    monkeypatch.setattr(svc, "_ps", fake_ps)

    log_path = tmp_path / "logs" / "daemon.log"
    info = svc.install(tmp_path / "animus.exe", log_path)

    # Log dir auto-created
    assert log_path.parent.exists()
    # Install script mentioned the daemon command + log file
    install_script = captured["scripts"][0]
    assert "Register-ScheduledTask" in install_script
    assert "daemon --log-file" in install_script
    assert info.installed is True
    assert info.running is True


def test_windows_status_not_installed(monkeypatch):
    monkeypatch.setattr(svc, "detect_platform", lambda: "windows")
    monkeypatch.setattr(svc, "_ps", lambda *a, **kw: _fake_completed(stdout="__NONE__"))
    info = svc.status()
    assert info.installed is False
    assert info.running is False


def test_windows_uninstall(monkeypatch):
    monkeypatch.setattr(svc, "detect_platform", lambda: "windows")
    monkeypatch.setattr(svc, "_ps", lambda *a, **kw: _fake_completed())
    info = svc.uninstall()
    assert info.installed is False
    assert "uninstalled" in info.detail
