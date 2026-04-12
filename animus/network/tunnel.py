"""Tunnel management — secure connectivity without admin privileges."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import AnimusConfig

logger = logging.getLogger("animus.tunnel")


@dataclass
class TunnelInfo:
    """Information about an active tunnel."""

    mode: str
    local_port: int
    remote_host: str
    remote_port: int
    pid: Optional[int] = None
    process: Optional[subprocess.Popen] = None


class TunnelManager:
    """Manages secure tunnels to the VPS hub.

    Supported modes (all work WITHOUT admin/root on the client):

    1. ssh     — SSH reverse tunnel (requires SSH key, most portable)
    2. chisel  — HTTP/WebSocket tunnel (single binary, no SSH needed)
    3. cloudflared — Cloudflare Tunnel (free tier, HTTPS out of the box)
    4. none    — Direct connection (hub is publicly accessible or same network)

    Design principle: clients always connect OUTBOUND to the hub,
    so no firewall/admin changes needed on the client side.
    """

    def __init__(self, config: AnimusConfig):
        self.config = config
        self._tunnel: Optional[TunnelInfo] = None

    async def start(self) -> TunnelInfo | None:
        mode = self.config.tunnel_mode
        if mode == "none":
            logger.info("No tunnel configured — using direct connection")
            return None
        elif mode == "ssh":
            return await self._start_ssh_tunnel()
        elif mode == "chisel":
            return await self._start_chisel_tunnel()
        elif mode == "cloudflared":
            return await self._start_cloudflared()
        else:
            logger.error("Unknown tunnel mode: %s", mode)
            return None

    async def stop(self) -> None:
        if self._tunnel and self._tunnel.process:
            self._tunnel.process.terminate()
            try:
                self._tunnel.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._tunnel.process.kill()
            logger.info("Tunnel stopped")
            self._tunnel = None

    # ── SSH Tunnel ──

    async def _start_ssh_tunnel(self) -> TunnelInfo:
        """Start an SSH reverse tunnel.

        Creates: local:local_port -> ssh -> remote:remote_port
        The hub listens on remote_port; we forward our local connections there.

        No admin required — just an SSH key.
        """
        local_port = self.config.server_port
        ssh_cmd = [
            "ssh",
            "-N",  # No command execution
            "-T",  # No PTY
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-p", str(self.config.tunnel_ssh_port),
            "-L", f"{local_port}:127.0.0.1:{self.config.tunnel_remote_port}",
        ]

        if self.config.tunnel_ssh_key:
            ssh_cmd.extend(["-i", self.config.tunnel_ssh_key])

        ssh_cmd.append(f"{self.config.tunnel_ssh_user}@{self.config.tunnel_ssh_host}")

        logger.info("Starting SSH tunnel: localhost:%d -> %s:%d",
                     local_port, self.config.tunnel_ssh_host, self.config.tunnel_remote_port)

        proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        # Wait a moment to see if it failed immediately
        await asyncio.sleep(2)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"SSH tunnel failed to start: {stderr}")

        self._tunnel = TunnelInfo(
            mode="ssh",
            local_port=local_port,
            remote_host=self.config.tunnel_ssh_host,
            remote_port=self.config.tunnel_remote_port,
            pid=proc.pid,
            process=proc,
        )
        logger.info("SSH tunnel established (PID %d)", proc.pid)
        return self._tunnel

    # ── Chisel Tunnel ──

    async def _start_chisel_tunnel(self) -> TunnelInfo:
        """Start a chisel tunnel.

        Chisel: https://github.com/jpillora/chisel
        Single Go binary, works over HTTP/WS, no admin needed.

        The hub runs `chisel server --port 8315 --key SECRET`
        Client runs `chisel client hub:8315 local:8314:127.0.0.1:8314`
        """
        chisel_bin = shutil.which("chisel")
        if not chisel_bin:
            # Try local bin
            local_bin = self.config.data_dir / ("chisel.exe" if sys.platform == "win32" else "chisel")
            if local_bin.exists():
                chisel_bin = str(local_bin)
            else:
                raise RuntimeError(
                    "chisel not found. Download from https://github.com/jpillora/chisel/releases "
                    f"and place in {self.config.data_dir} or your PATH"
                )

        local_port = self.config.server_port
        server_url = f"http://{self.config.tunnel_ssh_host}:8315"
        forward = f"{local_port}:127.0.0.1:{self.config.tunnel_remote_port}"

        cmd = [chisel_bin, "client", server_url, forward]

        logger.info("Starting chisel tunnel: %s -> %s", forward, server_url)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        await asyncio.sleep(2)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"Chisel tunnel failed: {stderr}")

        self._tunnel = TunnelInfo(
            mode="chisel",
            local_port=local_port,
            remote_host=self.config.tunnel_ssh_host,
            remote_port=self.config.tunnel_remote_port,
            pid=proc.pid,
            process=proc,
        )
        logger.info("Chisel tunnel established (PID %d)", proc.pid)
        return self._tunnel

    # ── Cloudflared ──

    async def _start_cloudflared(self) -> TunnelInfo:
        """Start a Cloudflare Tunnel (free, no admin, HTTPS built-in).

        Requires `cloudflared` binary and a Cloudflare account.
        Zero-config mode: `cloudflared tunnel --url http://localhost:8314`
        """
        cf_bin = shutil.which("cloudflared")
        if not cf_bin:
            local_bin = self.config.data_dir / (
                "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
            )
            if local_bin.exists():
                cf_bin = str(local_bin)
            else:
                raise RuntimeError(
                    "cloudflared not found. Download from "
                    "https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/"
                )

        cmd = [cf_bin, "tunnel", "--url", f"http://localhost:{self.config.server_port}"]

        logger.info("Starting Cloudflare tunnel for localhost:%d", self.config.server_port)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        self._tunnel = TunnelInfo(
            mode="cloudflared",
            local_port=self.config.server_port,
            remote_host="cloudflare",
            remote_port=443,
            pid=proc.pid,
            process=proc,
        )
        logger.info("Cloudflare tunnel starting (PID %d) — URL will appear in logs", proc.pid)
        return self._tunnel
