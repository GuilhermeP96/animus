"""Tests for animus.network.tunnel — TunnelManager."""

from unittest.mock import patch, MagicMock

import pytest

from animus.config import AnimusConfig
from animus.network.tunnel import TunnelManager, TunnelInfo


@pytest.fixture
def tunnel_mgr(config):
    config.tunnel_mode = "none"
    return TunnelManager(config)


class TestTunnelStart:
    @pytest.mark.asyncio
    async def test_none_mode_returns_none(self, tunnel_mgr):
        result = await tunnel_mgr.start()
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_mode_returns_none(self, tunnel_mgr):
        tunnel_mgr.config.tunnel_mode = "unknown_xyz"
        result = await tunnel_mgr.start()
        assert result is None

    @pytest.mark.asyncio
    async def test_ssh_without_binary_raises(self, tunnel_mgr):
        tunnel_mgr.config.tunnel_mode = "ssh"
        tunnel_mgr.config.tunnel_ssh_host = "example.com"
        tunnel_mgr.config.tunnel_ssh_user = "user"
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 1  # immediate exit = failure
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = b"Connection refused"
            mock_popen.return_value = mock_proc
            with pytest.raises(RuntimeError, match="SSH tunnel failed"):
                await tunnel_mgr._start_ssh_tunnel()

    @pytest.mark.asyncio
    async def test_chisel_not_found_raises(self, tunnel_mgr):
        tunnel_mgr.config.tunnel_ssh_host = "example.com"
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="chisel not found"):
                await tunnel_mgr._start_chisel_tunnel()

    @pytest.mark.asyncio
    async def test_cloudflared_not_found_raises(self, tunnel_mgr):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="cloudflared not found"):
                await tunnel_mgr._start_cloudflared()


class TestTunnelStop:
    @pytest.mark.asyncio
    async def test_stop_no_tunnel(self, tunnel_mgr):
        await tunnel_mgr.stop()
        assert tunnel_mgr._tunnel is None

    @pytest.mark.asyncio
    async def test_stop_terminates_process(self, tunnel_mgr):
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        tunnel_mgr._tunnel = TunnelInfo(
            mode="ssh",
            local_port=8314,
            remote_host="example.com",
            remote_port=8314,
            pid=12345,
            process=mock_proc,
        )
        await tunnel_mgr.stop()
        mock_proc.terminate.assert_called_once()
        assert tunnel_mgr._tunnel is None


class TestTunnelInfo:
    def test_dataclass_fields(self):
        info = TunnelInfo(mode="ssh", local_port=8314, remote_host="h", remote_port=8315)
        assert info.mode == "ssh"
        assert info.pid is None
        assert info.process is None
