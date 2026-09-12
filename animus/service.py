"""Cross-platform service installer for the Animus peer daemon.

Wraps the OS-native scheduler so a user can run

    animus service install
    animus service status
    animus service stop
    animus service uninstall

instead of remembering ``Register-ScheduledTask`` / ``systemctl --user`` /
``launchctl bootstrap``.

The module is intentionally side-effect-free at import time: every helper
takes the bits it needs (executable path, log path, …) explicitly so the
unit tests can drive the public surface without touching the host's real
service manager.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SERVICE_NAME = "AnimusPeerDaemon"
SYSTEMD_UNIT = "animus-peer.service"
LAUNCHD_LABEL = "com.datano.animus.peer"


@dataclass
class ServiceInfo:
    """Snapshot of the installed service state."""

    platform: str  # "windows" | "linux-systemd" | "darwin-launchd" | "unsupported"
    installed: bool
    running: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "installed": self.installed,
            "running": self.running,
            "detail": self.detail,
        }


def detect_platform() -> str:
    """Return the canonical service backend name for the current OS.

    The string is also what every other helper in this module branches on,
    so swapping the return value (e.g. in tests) lets us exercise each code
    path on any host.
    """
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "darwin-launchd"
    if system == "Linux":
        # We always target the per-user systemd instance — peers run with
        # the user's identity (their Copilot logs, their MCP knowledge
        # graph, etc.), so there's no good reason to demand sudo.
        if shutil.which("systemctl"):
            return "linux-systemd"
    return "unsupported"


# ── Windows (Scheduled Task) ─────────────────────────────────────────────


def _ps(script: str, *, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet, returning the CompletedProcess.

    Uses ``-NoProfile`` for determinism and ``-Command`` instead of ``-File``
    so callers can inline short scripts. ``capture=True`` is the default —
    we only stream output for the rare interactive command.
    """
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=capture,
        text=True,
        check=False,
    )


def _windows_install(animus_exe: Path, log_path: Path) -> ServiceInfo:
    """Register a Scheduled Task that runs ``animus daemon`` at logon.

    The task is configured to:

    * trigger on logon for the current user (``-AtLogOn``),
    * survive suspend/resume and battery transitions,
    * restart the process automatically up to 3 times if it dies.

    Logs are wired by passing ``--log-file`` so the daemon writes to a file
    instead of disappearing into a hidden console.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # The task action must be an executable + arguments. We pass the log
    # path explicitly via the daemon's own flag.
    # Run through Python, not the generated ``animus.exe`` launcher. Windows
    # locks a running executable, which can prevent pip from replacing that
    # console entry point during a self-update.
    python_exe = animus_exe.parent / "python.exe"
    args = f'-m animus.cli daemon --log-file "{log_path}"'
    # ``RestartCount 999`` + ``IgnoreNew`` underwrites the self-update flow:
    # when the daemon detects a new version it exits with code 75; the
    # Scheduled Task respawns it within a minute and the new code goes live
    # with no manual intervention. ``IgnoreNew`` blocks the supervisor from
    # double-launching us while pip is still mid-install.
    script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute '{python_exe}' -Argument '{args}'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName '{SERVICE_NAME}' -Action $action `
    -Trigger $trigger -Settings $set `
    -Description 'Animus Peer collector + sync daemon (self-updating)' -Force | Out-Null
Start-ScheduledTask -TaskName '{SERVICE_NAME}'
"""
    proc = _ps(script)
    if proc.returncode != 0:
        return ServiceInfo("windows", False, False, proc.stderr.strip() or proc.stdout.strip())
    return _windows_status()


def _windows_uninstall() -> ServiceInfo:
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
Stop-ScheduledTask -TaskName '{SERVICE_NAME}'
Unregister-ScheduledTask -TaskName '{SERVICE_NAME}' -Confirm:$false
"""
    _ps(script)
    return ServiceInfo("windows", False, False, "uninstalled")


def _windows_status() -> ServiceInfo:
    script = f"""
$t = Get-ScheduledTask -TaskName '{SERVICE_NAME}' -ErrorAction SilentlyContinue
if ($null -eq $t) {{ Write-Output '__NONE__'; exit 0 }}
$state = $t.State.ToString()
$info = $t | Get-ScheduledTaskInfo
Write-Output "$state|$($info.LastRunTime)|$($info.LastTaskResult)"
"""
    proc = _ps(script)
    out = (proc.stdout or "").strip()
    if not out or out == "__NONE__":
        return ServiceInfo("windows", False, False, "not installed")
    state, last_run, last_result = (out.split("|", 2) + ["", "", ""])[:3]
    running = state == "Running"
    detail = f"state={state} last_run={last_run} last_result={last_result}"
    return ServiceInfo("windows", True, running, detail)


def _windows_start() -> ServiceInfo:
    _ps(f"Start-ScheduledTask -TaskName '{SERVICE_NAME}'")
    return _windows_status()


def _windows_stop() -> ServiceInfo:
    _ps(f"Stop-ScheduledTask -TaskName '{SERVICE_NAME}'")
    return _windows_status()


# ── Linux (systemd --user) ───────────────────────────────────────────────


def _systemd_unit_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "systemd" / "user" / SYSTEMD_UNIT


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True, check=False,
    )


def _systemd_install(animus_exe: Path, log_path: Path) -> ServiceInfo:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    unit = _systemd_unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    # ``Restart=always`` + a short ``RestartSec`` so the self-updater can do
    # ``os.execv`` (preferred path) or ``sys.exit(RESTART_EXIT_CODE)``
    # (fallback) and trust systemd to bring the new code online quickly.
    # ``SuccessExitStatus=75`` keeps that sentinel exit out of the failure
    # counters in ``systemctl status``.
    unit.write_text(f"""[Unit]
Description=Animus Peer collector + sync daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={animus_exe} daemon --log-file {log_path}
Restart=always
RestartSec=5s
SuccessExitStatus=75
StandardOutput=append:{log_path}
StandardError=append:{log_path}

[Install]
WantedBy=default.target
""")
    _systemctl("daemon-reload")
    enable = _systemctl("enable", "--now", SYSTEMD_UNIT)
    if enable.returncode != 0:
        return ServiceInfo(
            "linux-systemd", False, False,
            (enable.stderr or enable.stdout or "").strip(),
        )
    return _systemd_status()


def _systemd_uninstall() -> ServiceInfo:
    _systemctl("disable", "--now", SYSTEMD_UNIT)
    unit = _systemd_unit_path()
    if unit.exists():
        unit.unlink()
    _systemctl("daemon-reload")
    return ServiceInfo("linux-systemd", False, False, "uninstalled")


def _systemd_status() -> ServiceInfo:
    unit = _systemd_unit_path()
    if not unit.exists():
        return ServiceInfo("linux-systemd", False, False, "not installed")
    is_active = _systemctl("is-active", SYSTEMD_UNIT)
    running = is_active.stdout.strip() == "active"
    return ServiceInfo("linux-systemd", True, running, is_active.stdout.strip())


def _systemd_start() -> ServiceInfo:
    _systemctl("start", SYSTEMD_UNIT)
    return _systemd_status()


def _systemd_stop() -> ServiceInfo:
    _systemctl("stop", SYSTEMD_UNIT)
    return _systemd_status()


# ── macOS (launchd) ──────────────────────────────────────────────────────


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_install(animus_exe: Path, log_path: Path) -> ServiceInfo:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    plist = _launchd_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>{animus_exe}</string>
      <string>daemon</string>
      <string>--log-file</string>
      <string>{log_path}</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>{log_path}</string>
    <key>StandardErrorPath</key><string>{log_path}</string>
</dict>
</plist>
""")
    uid = os.getuid()  # type: ignore[attr-defined]
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
        capture_output=True, text=True, check=False,
    )
    return _launchd_status()


def _launchd_uninstall() -> ServiceInfo:
    plist = _launchd_plist_path()
    uid = os.getuid()  # type: ignore[attr-defined]
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{LAUNCHD_LABEL}"],
        capture_output=True, text=True, check=False,
    )
    if plist.exists():
        plist.unlink()
    return ServiceInfo("darwin-launchd", False, False, "uninstalled")


def _launchd_status() -> ServiceInfo:
    plist = _launchd_plist_path()
    if not plist.exists():
        return ServiceInfo("darwin-launchd", False, False, "not installed")
    proc = subprocess.run(
        ["launchctl", "list", LAUNCHD_LABEL],
        capture_output=True, text=True, check=False,
    )
    running = proc.returncode == 0 and "PID" in proc.stdout
    return ServiceInfo("darwin-launchd", True, running, proc.stdout.strip()[:200])


def _launchd_start() -> ServiceInfo:
    uid = os.getuid()  # type: ignore[attr-defined]
    subprocess.run(
        ["launchctl", "kickstart", f"gui/{uid}/{LAUNCHD_LABEL}"],
        capture_output=True, text=True, check=False,
    )
    return _launchd_status()


def _launchd_stop() -> ServiceInfo:
    uid = os.getuid()  # type: ignore[attr-defined]
    subprocess.run(
        ["launchctl", "kill", "TERM", f"gui/{uid}/{LAUNCHD_LABEL}"],
        capture_output=True, text=True, check=False,
    )
    return _launchd_status()


# ── Public dispatch ──────────────────────────────────────────────────────


def default_log_path(data_dir: Path) -> Path:
    """Where the daemon writes when running headless via the service manager."""
    return data_dir / "daemon.log"


def default_animus_exe() -> Path:
    """Best-effort path to the ``animus`` console script of the *current* venv.

    Falls back to a bare ``animus`` so PATH-based resolution still works in
    development checkouts.
    """
    if sys.platform == "win32":
        candidate = Path(sys.executable).parent / "animus.exe"
    else:
        candidate = Path(sys.executable).parent / "animus"
    return candidate if candidate.exists() else Path("animus")


def install(animus_exe: Path, log_path: Path) -> ServiceInfo:
    backend = detect_platform()
    if backend == "windows":
        return _windows_install(animus_exe, log_path)
    if backend == "linux-systemd":
        return _systemd_install(animus_exe, log_path)
    if backend == "darwin-launchd":
        return _launchd_install(animus_exe, log_path)
    return ServiceInfo(backend, False, False, "no supported service manager on this OS")


def uninstall() -> ServiceInfo:
    backend = detect_platform()
    if backend == "windows":
        return _windows_uninstall()
    if backend == "linux-systemd":
        return _systemd_uninstall()
    if backend == "darwin-launchd":
        return _launchd_uninstall()
    return ServiceInfo(backend, False, False, "unsupported")


def status() -> ServiceInfo:
    backend = detect_platform()
    if backend == "windows":
        return _windows_status()
    if backend == "linux-systemd":
        return _systemd_status()
    if backend == "darwin-launchd":
        return _launchd_status()
    return ServiceInfo(backend, False, False, "unsupported")


def start() -> ServiceInfo:
    backend = detect_platform()
    if backend == "windows":
        return _windows_start()
    if backend == "linux-systemd":
        return _systemd_start()
    if backend == "darwin-launchd":
        return _launchd_start()
    return ServiceInfo(backend, False, False, "unsupported")


def stop() -> ServiceInfo:
    backend = detect_platform()
    if backend == "windows":
        return _windows_stop()
    if backend == "linux-systemd":
        return _systemd_stop()
    if backend == "darwin-launchd":
        return _launchd_stop()
    return ServiceInfo(backend, False, False, "unsupported")
