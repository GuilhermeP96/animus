# Animus Peer — Manual Installation Guide for GitHub Copilot

> **Audience:** GitHub Copilot Chat in VS Code, acting as an autonomous agent on
> the user's behalf. Follow these steps **literally** if the bundled
> `install.sh` / `install.bat` could not be executed (restricted shell, no
> internet to GitHub raw, custom Python paths, etc.).
>
> **Pre-baked context lives in `peer.env`** (next to this file). It contains
> `ANIMUS_HUB_URL`, `ANIMUS_SERVER_SECRET`, `ANIMUS_NODE_ID`, `ANIMUS_NODE_NAME`,
> and the upstream repo URL. **Never echo the secret to the chat surface or
> commit it to a repository.**

---

## 0. Inputs you already have

Read `peer.env` from this kit's folder. Parse the `KEY=VALUE` lines and use
those values everywhere this guide says `$ANIMUS_*`. Treat the secret as
sensitive — pass it via environment variables, never as a CLI flag.

If `peer.env` is missing, ask the user to regenerate the ZIP from
`https://<hub>/admin/peers` → button **"Generate Installer ZIP"**.

---

## 1. Verify prerequisites

Run, in a terminal:

| Check        | Command                                  | Required        |
|--------------|------------------------------------------|-----------------|
| Python ≥3.11 | `python3 --version` (Linux/macOS) `python --version` (Windows) | mandatory       |
| Git          | `git --version`                          | mandatory       |
| pip          | `python3 -m pip --version`               | mandatory       |
| systemd      | `systemctl --version` (Linux only)       | optional (daemon) |
| schtasks     | `schtasks /?` (Windows only)             | optional (daemon) |

If Python is missing:
- **Linux (Debian/Ubuntu):** `sudo apt-get install -y python3 python3-venv python3-pip git curl`
- **Linux (Fedora):** `sudo dnf install -y python3 python3-pip git curl`
- **macOS:** `brew install python@3.13 git`
- **Windows:** `winget install --id Python.Python.3.13 --silent`

---

## 2. Clone the Animus source

Pick an install dir:

- Linux as root → `/opt/animus`
- Linux as user → `$HOME/.local/animus`
- macOS         → `$HOME/.local/animus`
- Windows       → `%LOCALAPPDATA%\animus`

```bash
git clone --branch "$ANIMUS_BRANCH" --depth 1 "$ANIMUS_REPO_URL" "$INSTALL_DIR"
```

If `git clone` fails because of network rules, download
`$ANIMUS_REPO_URL/archive/refs/heads/$ANIMUS_BRANCH.zip`, extract, and treat the
extracted folder as `$INSTALL_DIR`.

---

## 3. Create venv and install the package

```bash
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -e "$INSTALL_DIR"
```

On Windows replace `bin/` with `Scripts\` and use `python.exe`/`pip.exe`.

After this step, the `animus` CLI must exist:
- Linux/macOS: `$INSTALL_DIR/.venv/bin/animus`
- Windows:    `$INSTALL_DIR\.venv\Scripts\animus.exe`

---

## 4. Configure the peer

Run **once**, with the env vars from `peer.env` exported:

```bash
export ANIMUS_NODE_ID="$ANIMUS_NODE_ID"
export ANIMUS_NODE_NAME="$ANIMUS_NODE_NAME"
"$INSTALL_DIR/.venv/bin/animus" init
"$INSTALL_DIR/.venv/bin/animus" config-set hub_url       "$ANIMUS_HUB_URL"
"$INSTALL_DIR/.venv/bin/animus" config-set server_secret "$ANIMUS_SERVER_SECRET"
"$INSTALL_DIR/.venv/bin/animus" config-set node_id       "$ANIMUS_NODE_ID"
"$INSTALL_DIR/.venv/bin/animus" config-set node_name     "$ANIMUS_NODE_NAME"
```

Verify:

```bash
"$INSTALL_DIR/.venv/bin/animus" config-get hub_url
"$INSTALL_DIR/.venv/bin/animus" config-get node_id
```

---

## 5. First collect + sync (smoke test)

```bash
"$INSTALL_DIR/.venv/bin/animus" collect
"$INSTALL_DIR/.venv/bin/animus" sync
"$INSTALL_DIR/.venv/bin/animus" stats
```

Expected: `sync` completes with HTTP 200; `stats` shows non-zero memories.

If `sync` returns 401 → the `server_secret` in `peer.env` is wrong; ask the
user to re-reveal it on `https://<hub>/admin/peers`.

If `sync` returns connection refused → the hub URL is unreachable from this
machine (firewall, DNS).

---

## 6. Background daemon (optional, recommended)

### Linux with systemd (root)

Create `/etc/systemd/system/animus-peer.service`:

```ini
[Unit]
Description=Animus Peer — Collector + Sync Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/animus/.venv/bin/animus daemon
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now animus-peer.service
systemctl status animus-peer
```

### Linux as user

Place the same unit at `$HOME/.config/systemd/user/animus-peer.service`,
adjusting `ExecStart`, then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now animus-peer.service
loginctl enable-linger "$USER"   # so it survives logout
```

### Windows (Scheduled Task at logon)

```powershell
$animus  = "$env:LOCALAPPDATA\animus\.venv\Scripts\animus.exe"
$action  = New-ScheduledTaskAction  -Execute $animus -Argument 'daemon'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set     = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -RestartCount 3 `
              -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'AnimusPeerDaemon' -Action $action `
    -Trigger $trigger -Settings $set -Force
Start-ScheduledTask -TaskName 'AnimusPeerDaemon'
```

---

## 7. (Optional) Wire up MCP for VS Code Copilot

If the user wants the `animus_*` MCP tools inside Copilot Chat on **this**
machine, add to `~/.vscode-server/data/User/mcp.json` (Linux) or
`%APPDATA%\Code\User\mcp.json` (Windows):

```json
{
  "servers": {
    "animus": {
      "type": "stdio",
      "command": "<INSTALL_DIR>/.venv/bin/animus",
      "args": ["mcp"],
      "env": {
        "ANIMUS_DATA_DIR": "<INSTALL_DIR>/data"
      }
    }
  }
}
```

Restart VS Code; the seven tools (`animus_search`, `animus_recall`,
`animus_remember`, `animus_forget`, `animus_stats`, `animus_collect`,
`animus_context`, `animus_timeline`) should appear in the tool picker.

---

## 8. Validation checklist

- [ ] `animus stats` returns counts > 0
- [ ] `animus sync` exits 0
- [ ] Hub UI `/admin/peers` lists this `node_id` as **online**
- [ ] (If MCP) `animus_stats` is callable from Copilot Chat
- [ ] Daemon active (`systemctl status` / `Get-ScheduledTask`)

---

## 9. Troubleshooting

| Symptom                                    | Cause / Fix                                                  |
|--------------------------------------------|--------------------------------------------------------------|
| `pip install -e .` fails: `error: externally-managed-environment` | The venv was not activated. Use the **venv's** `pip`, not the system one. |
| `animus: command not found`                | Activate the venv or use the absolute path to `.venv/bin/animus`. |
| `sync` → HTTP 401                          | Wrong secret; regenerate the kit from the hub.               |
| `sync` → SSL error                         | Old CA bundle. Update certs (`pip install --upgrade certifi`). |
| `sync` → `Temporary failure in name resolution` / connection refused | `hub_url` points at an internal Docker IP (`172.x`, `10.x`) that isn't routable from this host. Use the **public HTTPS URL** (e.g. `https://animus.datano.com.br`) — `peer.env` is generated with the right value; only an edited config drifts. |
| `collect` returns 0 memories               | VS Code data dir not readable. Run as the same user that uses VS Code. |
| Hub doesn't see this peer in `/admin/peers`| Daemon not running, or `node_id` collides with another peer. |

---

## 10. Cleanup / re-install

```bash
# Linux/macOS
sudo systemctl disable --now animus-peer.service 2>/dev/null || true
rm -rf "$INSTALL_DIR"

# Windows
Unregister-ScheduledTask -TaskName 'AnimusPeerDaemon' -Confirm:$false
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\animus"
```

Then re-run `install.sh` / `install.bat` from a freshly downloaded ZIP.

---

**End of guide.** When all checklist items in §8 pass, report back to the user:
"Animus peer `<NODE_ID>` registered on hub `<HUB_URL>` and syncing."
