"""Self-update — peers pick up new Animus releases automatically.

The flow is intentionally tiny:

1. The peer polls ``GET /api/version`` on the hub. The endpoint is unauth'd
   (it leaks nothing more than the running version) and returns:

       {
         "latest":   "0.5.0",        # canonical hub version
         "min_compat": "0.4.0",      # peers below this MUST upgrade
         "channel":  "stable",       # for future use; clients ignore
         "install_url": "git+https://github.com/.../animus.git",
         "git_ref":  "main"          # branch/tag pip should pull
       }

2. The peer compares ``latest`` against :mod:`animus.__version__`. If the
   hub is newer, it downloads the Hub's authenticated ``package_url``, verifies
   its version and SHA-256 metadata, and prepares that wheel for installation.
   Older hubs fall back to

       pip install --upgrade --quiet <install_url>@<git_ref>

   for the same interpreter. On POSIX, ``pip`` runs synchronously. On Windows,
   a detached helper waits for the daemon to exit, closes legacy Animus console
   launchers that still hold the venv, and only then invokes pip.

3. On POSIX success, the peer re-execs itself with ``os.execv``. A Windows
   peer exits with code 75 so the helper can replace locked files; its Scheduled
   Task restarts the daemon with the new package.

The module is conservative on purpose:

* It refuses to upgrade if it can't determine ``sys.executable`` lives in a
  writable venv (e.g. when Animus was installed as a system package or via
  ``pipx``). Falls back to a log line + a ``need_upgrade`` flag in stats.

* It enforces a minimum check interval (``update_check_interval_seconds``)
  so a chatty hub or a buggy daemon loop can't degenerate into a pip-storm.

* Every external call is wrapped — a hub outage or a pip transient failure
  never escapes ``check_and_apply()``: the daemon keeps running on the old
  version, retries on the next cycle.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from .. import __version__ as CURRENT_VERSION
from ..config import AnimusConfig
from .crypto import create_auth_header

logger = logging.getLogger("animus.updater")

# Sentinel exit code the daemon uses when it cleanly exits to be respawned
# with new code. systemd + Scheduled Task already restart on non-zero exit;
# we don't rely on SuccessExitStatus magic for that reason.
RESTART_EXIT_CODE = 75  # EX_TEMPFAIL — "try again later"

DEFAULT_REPO = "git+https://github.com/GuilhermeP96/animus.git"

# On Windows pip cannot replace a console launcher while that launcher is the
# running daemon (or an MCP process). The update is therefore handed to a
# detached PowerShell helper and the caller exits with RESTART_EXIT_CODE.
_deferred_update_pending = False


@dataclass
class VersionInfo:
    latest: str
    min_compat: str = ""
    channel: str = "stable"
    install_url: str = DEFAULT_REPO
    git_ref: str = "main"
    package_url: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "VersionInfo":
        return cls(
            latest=str(data.get("latest") or "").strip(),
            min_compat=str(data.get("min_compat") or "").strip(),
            channel=str(data.get("channel") or "stable").strip(),
            install_url=str(data.get("install_url") or DEFAULT_REPO).strip(),
            git_ref=str(data.get("git_ref") or "main").strip(),
            package_url=str(data.get("package_url") or "").strip(),
            notes=str(data.get("notes") or "").strip(),
        )


# ── version comparison ──────────────────────────────────────────────────


def _parse(version: str) -> tuple[int, ...]:
    """Loose semver parse: ``"0.5.1-rc.2"`` → ``(0, 5, 1)``.

    Pre-release / build metadata (anything after ``-`` or ``+``) is stripped
    *before* splitting on ``.`` — without this an ``rc`` suffix would inflate
    the tuple length and make ``0.5.0-rc.1`` compare greater than ``0.5.0``,
    which is the opposite of semver's rule.
    """
    base = (version or "").split("-", 1)[0].split("+", 1)[0]
    out: list[int] = []
    for chunk in base.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        out.append(int(digits) if digits else 0)
    # Pad to length 3 so 0.5 vs 0.5.0 compare equal.
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def is_newer(remote: str, local: str) -> bool:
    if not remote:
        return False
    return _parse(remote) > _parse(local)


# ── hub query ───────────────────────────────────────────────────────────


def fetch_latest(config: AnimusConfig, timeout: float = 10.0) -> Optional[VersionInfo]:
    """Ask the hub for its latest release info. ``None`` on any failure."""
    if not config.hub_url:
        return None
    base = config.hub_url.replace("wss://", "https://").replace("ws://", "http://")
    url = base.rstrip("/") + "/api/version"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                logger.warning("Version probe failed: HTTP %d", resp.status_code)
                return None
            return VersionInfo.from_dict(resp.json())
    except Exception as exc:
        logger.warning("Version probe error: %s", exc)
        return None


# ── apply ────────────────────────────────────────────────────────────────


def _pip_exe() -> Path | None:
    """The pip that lives next to the running Python — same venv guarantee.

    Resolved once per call (no caching) because the daemon's lifetime spans
    actual upgrades, after which the pip we point at may have moved (a fresh
    re-exec gets a fresh resolution).
    """
    py_dir = Path(sys.executable).parent
    if os.name == "nt":
        candidates = [py_dir / "pip.exe", py_dir / "Scripts" / "pip.exe"]
    else:
        candidates = [py_dir / "pip", py_dir / "pip3"]
    for c in candidates:
        if c.exists():
            return c
    return None


def _is_writable_install() -> bool:
    """Refuse to self-upgrade when the install is read-only or system-wide.

    Heuristic: the site-packages dir of the running interpreter must be
    writable. Catches the OS-package and pipx cases without false positives.
    """
    try:
        import animus

        pkg_root = Path(animus.__file__).resolve().parent.parent
        return os.access(pkg_root, os.W_OK)
    except Exception:
        return False


def download_hub_package(config: AnimusConfig, info: VersionInfo) -> Path | None:
    """Download and verify the Hub's current wheel over the peer HMAC channel."""
    if not info.package_url or not config.hub_url or not config.server_secret:
        return None
    hub = config.hub_url.rstrip("/") + "/"
    url = urljoin(hub, info.package_url)
    hub_origin = urlparse(hub)
    package_origin = urlparse(url)
    if (package_origin.scheme, package_origin.netloc) != (hub_origin.scheme, hub_origin.netloc):
        logger.error("Refusing package URL outside the configured Hub origin")
        return None
    headers = create_auth_header(config.server_secret, config.node_id, body=None)
    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
        if response.status_code != 200:
            logger.error("Hub package download failed: HTTP %d", response.status_code)
            return None
    except Exception as exc:
        logger.error("Hub package download failed: %s", exc)
        return None

    filename = response.headers.get("X-Animus-Package-Filename", "")
    served_version = response.headers.get("X-Animus-Version", "")
    if served_version != info.latest:
        logger.error("Hub package version mismatch: expected=%s got=%s", info.latest, served_version)
        return None
    if not re.fullmatch(r"animus-[A-Za-z0-9_.+-]+\.whl", filename):
        logger.error("Hub returned an invalid package filename")
        return None
    expected = response.headers.get("X-Animus-Package-SHA256", "").lower()
    actual = hashlib.sha256(response.content).hexdigest()
    if not expected or not hmac.compare_digest(expected, actual):
        logger.error("Hub package checksum mismatch")
        return None

    update_dir = config.data_dir / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    destination = update_dir / filename
    temporary = update_dir / f".{filename}.tmp"
    temporary.write_bytes(response.content)
    temporary.replace(destination)
    logger.info("Downloaded signed Hub package: %s", destination)
    return destination


def update_is_deferred() -> bool:
    """Whether this process must exit so a Windows update helper can proceed."""
    return _deferred_update_pending


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _defer_windows_update(cmd: list[str], latest: str) -> bool:
    """Launch an updater that waits for this process and releases EXE locks."""
    global _deferred_update_pending

    # Keep these as strings: pathlib chooses WindowsPath from os.name at call
    # time, which also makes cross-platform validation of this branch fail.
    scripts_dir = os.path.dirname(sys.executable)
    log_path = os.path.join(tempfile.gettempdir(), "animus-self-update.log")
    command = " ".join(_ps_quote(part) for part in cmd)
    script = f"""
$ErrorActionPreference = 'Continue'
$sourcePid = {os.getpid()}
while (Get-Process -Id $sourcePid -ErrorAction SilentlyContinue) {{
    Start-Sleep -Milliseconds 200
}}
Start-Sleep -Milliseconds 500
$scriptsDir = {_ps_quote(scripts_dir)}
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {{
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($scriptsDir, [StringComparison]::OrdinalIgnoreCase) -and
        $_.Name -like 'animus*.exe'
    }} | ForEach-Object {{
        & taskkill.exe /PID $_.ProcessId /T /F 2>$null | Out-Null
    }}
& {command} *>> {_ps_quote(log_path)}
$rc = $LASTEXITCODE
Add-Content -LiteralPath {_ps_quote(log_path)} -Value ({_ps_quote(f'update v{latest} exit=')} + $rc)
exit $rc
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except OSError as exc:
        logger.error("Could not launch deferred Windows updater: %s", exc)
        return False
    _deferred_update_pending = True
    logger.info("Windows self-update staged; helper log: %s", log_path)
    return True


def apply_update(
    info: VersionInfo,
    *,
    allow_pre: bool = False,
    config: AnimusConfig | None = None,
) -> bool:
    """Run ``pip install --upgrade`` for the new version. Returns success."""
    if not _is_writable_install():
        logger.error(
            "Refusing self-update: install dir is not writable (system package "
            "or read-only venv). Re-install Animus manually as a writable venv."
        )
        return False

    pip = _pip_exe()
    if pip is None:
        logger.error("Refusing self-update: no pip alongside %s", sys.executable)
        return False

    if info.package_url:
        if config is None:
            logger.error("Hub package update requires peer configuration")
            return False
        package = download_hub_package(config, info)
        if package is None:
            return False
        target = str(package)
    else:
        target = (
            f"{info.install_url}@{info.git_ref}"
            if "@" not in info.install_url else info.install_url
        )
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet",
           "--disable-pip-version-check", target]
    if allow_pre:
        cmd.insert(-1, "--pre")
    logger.info("Self-update → %s", target)
    if os.name == "nt":
        return _defer_windows_update(cmd, info.latest)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("Self-update timed out after 10 min")
        return False
    if proc.returncode != 0:
        logger.error(
            "pip install failed (rc=%d): %s",
            proc.returncode,
            (proc.stderr or proc.stdout)[:1500],
        )
        return False
    logger.info("Self-update succeeded — restarting into v%s", info.latest)
    return True


def restart_in_place() -> None:
    """Replace the running process with a fresh copy of itself.

    ``os.execv`` doesn't return on success — the new process inherits the
    PID. Falls back to ``sys.exit(RESTART_EXIT_CODE)`` so the supervisor
    restarts us via its own policy if execv refuses (Windows + frozen
    bundles do this; venv installs do not).
    """
    if update_is_deferred():
        logger.info("Exiting with %d so the Windows update helper can run", RESTART_EXIT_CODE)
        sys.exit(RESTART_EXIT_CODE)
    try:
        os.execv(sys.executable, [sys.executable, *sys.argv])
    except OSError as exc:
        logger.warning("os.execv failed (%s) — exiting with %d for supervisor restart",
                       exc, RESTART_EXIT_CODE)
        sys.exit(RESTART_EXIT_CODE)


# ── high-level orchestration ────────────────────────────────────────────


def check_and_apply(
    config: AnimusConfig,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[bool, VersionInfo | None]:
    """One-shot: probe the hub, decide, upgrade.

    Returns ``(restart_required, info)``. ``restart_required`` is True when a
    new version was installed and the caller should ``restart_in_place()``.

    The daemon ignores ``dry_run``; the CLI uses it for ``animus self-update
    --check``.
    """
    info = fetch_latest(config)
    if info is None or not info.latest:
        return False, info
    if not force and not is_newer(info.latest, CURRENT_VERSION):
        return False, info
    if dry_run:
        return True, info
    ok = apply_update(info, allow_pre=config.update_allow_pre, config=config)
    return (ok, info)
