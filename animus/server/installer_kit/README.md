# Animus Peer — Installer Kit

A self-contained installer for joining this machine to the Animus hub at
**{{HUB_URL}}** as node **`{{NODE_ID}}`** (`{{NODE_NAME}}`).

Everything you need is in this folder — no manual secret pasting.

## What's inside

| File          | Purpose                                                          |
|---------------|------------------------------------------------------------------|
| `peer.env`    | Pre-baked config: hub URL, HMAC secret, node id, node name.      |
| `install.sh`  | Linux / macOS one-shot installer.                                |
| `install.ps1` | Windows installer (PowerShell).                                  |
| `install.bat` | Windows double-click entry point (self-elevates, runs `.ps1`).   |
| `COPILOT.md`  | Step-by-step manual install for GitHub Copilot in VS Code.       |
| `README.md`   | This file.                                                       |

## Usage

### Linux / macOS

```bash
chmod +x install.sh
./install.sh
```

### Windows (preferred)

Double-click **`install.bat`**. Approve the UAC prompt.

### Windows (alternative)

Open PowerShell **as Administrator** in this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### GitHub Copilot in VS Code (no shell access)

Open `COPILOT.md` and ask Copilot Chat:

> Follow `COPILOT.md` literally to install the Animus peer. Use the values in
> `peer.env` for hub URL, secret, and node id.

The agent will run the installation step by step and verify each phase.

## What the installers do

1. Install missing prerequisites (Python ≥3.11, Git) via the system package manager.
2. `git clone` the canonical Animus repo (URL from `peer.env`).
3. Create a virtualenv and `pip install -e .` the package.
4. Apply the pre-baked config (hub URL, secret, node id, node name).
5. Run an initial `collect` + `sync` as a smoke test.
6. Register a background daemon (systemd unit on Linux; Scheduled Task on Windows).

## Security

- `peer.env` contains the **shared HMAC secret** for this hub. Anyone holding
  this file can push memories to **{{HUB_URL}}**. Treat it like a password.
- Do **not** commit `peer.env` to a git repository.
- To rotate: change `ANIMUS_SERVER_SECRET` in the hub's `.env`, restart the hub
  container, regenerate this kit, and re-run the installer on each peer.

## Regenerating

Open **{{HUB_URL}}/admin/peers** → **Generate Installer ZIP** to produce a
fresh kit with a new `node_id` (or override the name field first).

Generated: {{GENERATED_AT}}
