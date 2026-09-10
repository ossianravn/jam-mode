# Install JAM Mode 0.3

Extract the release archive. The resulting `jam-mode-marketplace` directory is a local Codex marketplace containing the plugin, MCP server, controller, named-agent routing layer, installers, tests, and documentation.

## Requirements

- Codex CLI installed, signed in, and available on `PATH`.
- Python 3.10 or newer.
- A new Codex Desktop or CLI session after installation or upgrade.
- The same `CODEX_HOME` for every Codex surface that should share JAM configuration, custom agents, authentication, sessions, and campaign state.

## Windows Desktop using WSL2 — recommended

1. In Codex Desktop Settings, switch the agent runtime from Windows native to **WSL**, then restart Desktop.
2. In WSL, point `CODEX_HOME` at the Windows Codex profile:

   ```bash
   export CODEX_HOME="/mnt/c/Users/<WindowsUser>/.codex"
   export PATH="$HOME/.local/bin:$PATH"
   ```

   Add both lines to `~/.bashrc` or `~/.zshrc` for future shells.

3. From the extracted marketplace directory:

   ```bash
   cd jam-mode-marketplace
   python3 plugins/jam-mode/scripts/validate_plugin.py plugins/jam-mode
   bash plugins/jam-mode/scripts/install-wsl.sh
   jam doctor
   jam models
   jam routing
   ```

4. Restart Desktop and open a new conversation. Use `@JAM Mode` in Desktop, `$jam-mode` in Codex CLI, or the `jam` companion command.

The installer:

- copies the marketplace to `$CODEX_HOME/jam-mode-marketplace` unless overridden;
- rewrites the bundled MCP launcher with absolute host paths;
- registers the local Codex marketplace;
- creates `~/.local/bin/jam` unless overridden;
- creates `$CODEX_HOME/jam-mode/config.toml` when absent;
- materializes marker-owned custom agents under `$CODEX_HOME/agents/jam_*.toml`.

Installation does not require a live model-catalog request. Campaign start and resume validate the requested roster against the current account through Codex App Server unless validation is disabled.

Current Codex releases manage first-time plugin activation in the app. After the
installer finishes, open **Settings > Plugins** and install JAM Mode, or choose
**Refresh** when it is already installed. Older Codex CLIs that expose
`codex plugin add` are activated directly by the installer.

## Native Windows

Use this path when Desktop runs the Windows-native Codex agent and native Windows has Codex CLI and Python 3.10 or newer on `PATH`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd jam-mode-marketplace
py -3 .\plugins\jam-mode\scripts\validate_plugin.py .\plugins\jam-mode
.\plugins\jam-mode\scripts\install-windows.ps1
jam doctor
jam models
jam routing
```

The installer creates `jam.cmd` under `%CODEX_HOME%\bin` by default. Add that directory to `PATH` when `jam` is not found in a new terminal.

Windows-native campaigns use Windows paths such as `C:\src\project`. WSL-hosted campaigns use Linux paths such as `/home/me/src/project`.

## Verify the routing layer

List models and advertised reasoning efforts:

```bash
jam models
```

Inspect the default resolved roster:

```bash
jam routing
```

A new install defaults to:

```text
policy: balanced
validation: fallback
child Ultra: disabled
parent Ultra: disabled
```

Select another policy:

```bash
jam routing --policy economy --validation fallback
jam routing --policy balanced --validation strict
jam routing --policy quality --validation fallback
jam routing --policy inherit
```

Create a custom roster:

```bash
jam routing \
  --policy custom \
  --model gpt-5.6-sol \
  --effort high \
  --role-model explorer=gpt-5.6-luna \
  --role-effort explorer=medium \
  --role-model implementer=gpt-5.6-terra \
  --role-effort implementer=high \
  --role-model reviewer=gpt-5.6-sol \
  --role-effort reviewer=high
```

The persisted routing defaults live at `$CODEX_HOME/jam-mode/config.toml`. Do not manually edit the generated `$CODEX_HOME/agents/jam_*.toml` files; use `jam routing` or `jam_configure_model_routing` so the config and agents stay synchronized. The MCP configuration tool accepts an optional paused campaign id, and `jam_refresh_campaign_routing` revalidates a paused campaign without changing its overrides.

## Quick local campaign

```bash
jam start \
  -C ~/src/project \
  --profile adaptive \
  --sandbox workspace-write \
  --model-policy balanced \
  --objective "Implement the requested feature, validate it, review it, update the relevant documentation, and stop when the acceptance criteria are verified." \
  --max-episodes 8 \
  --max-subagents 2
```

When `--boundaries` is omitted and network access is off, JAM creates conservative local-workspace boundaries. Explicit boundaries are required for `--network` and should be supplied for security-sensitive, production, third-party, credentialed, destructive, deployment, or publication work.

## Upgrade from JAM 0.1 or 0.2

Back up persistent state:

```bash
cp -a "$CODEX_HOME/jam-mode" "$CODEX_HOME/jam-mode.backup"
```

Run the 0.3 installer from the newly extracted release. Do not delete `$CODEX_HOME/jam-mode`.
On native Windows, close Codex Desktop and any running JAM controller before
upgrading so Windows can replace the marketplace directory atomically. If the
directory is locked, the installer restores the existing package and exits
without completing the upgrade.

WSL/Linux:

```bash
bash plugins/jam-mode/scripts/install-wsl.sh
```

Native Windows:

```powershell
.\plugins\jam-mode\scripts\install-windows.ps1
```

The installer refreshes the plugin source while preserving campaign data and existing routing settings. Native Windows installs write an absolute Python launcher and a fresh plugin build version before installation, keeping that configuration separate from older or generic cached packages. The installer reinstalls the plugin when the CLI supports it; otherwise choose **Refresh** for JAM Mode under **Settings > Plugins**. Start a new conversation to load the updated tools. On first use, JAM migrates the SQLite database in place. Version 0.1 research handoffs remain unchanged on disk and are normalized when read. Version 0.2 campaigns receive the 0.3 routing and telemetry columns.

Restart Codex Desktop and begin a new Desktop/CLI conversation after the upgrade.

## Managed-agent collision handling

JAM owns only personal custom-agent files containing:

```text
# JAM_MODE_MANAGED=1
```

It refuses to overwrite an unmarked file such as `$CODEX_HOME/agents/jam_reviewer.toml`.

It also refuses to start a campaign when the workspace contains `.codex/agents/jam_*.toml`, because project-scoped agents would override the personal JAM roster. Rename or remove the collision, then retry.

## Routing an existing campaign

A campaign’s roster is frozen at creation. Pause it before changing that roster:

```bash
jam pause <campaign-id>
jam routing <campaign-id> --policy quality
jam routing <campaign-id> --refresh
jam resume <campaign-id>
```

The active episode must finish before routing files can change.

## Diagnostic commands

```bash
jam doctor
jam models
jam routing
jam --json list
jam --json status
```

An empty campaign list is expected before the first campaign. `jam doctor` reports Codex, Python, state-path, routing-config, and managed-agent checks.

## Uninstall

WSL/Linux:

```bash
bash plugins/jam-mode/scripts/uninstall-wsl.sh
```

Native Windows:

```powershell
.\plugins\jam-mode\scripts\uninstall-windows.ps1
```

The uninstallers remove the plugin, marketplace source, companion launcher, and marker-owned JAM custom agents. They preserve `$CODEX_HOME/jam-mode`, including campaign history and routing configuration. Remove that directory manually only after its contents are no longer needed.
