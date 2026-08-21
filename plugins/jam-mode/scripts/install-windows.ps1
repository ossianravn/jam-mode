[CmdletBinding()]
param(
    [string]$Destination,
    [string]$BinDirectory
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = (Resolve-Path (Join-Path $ScriptDir "..\..\..")).Path
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
if (-not $Destination) { $Destination = Join-Path $CodexHome "jam-mode-marketplace" }
if (-not $BinDirectory) { $BinDirectory = Join-Path $CodexHome "bin" }
$PluginRoot = Join-Path $Destination "plugins\jam-mode"

$Codex = Get-Command codex -ErrorAction SilentlyContinue
if (-not $Codex) { throw "The Codex CLI is required and must be available on PATH." }

$Py = Get-Command py -ErrorAction SilentlyContinue
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Py -and -not $Python) { throw "Python 3.10 or newer is required (py -3 or python)." }

if ($Py) {
    & $Py.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is required." }
    $PythonCommand = $Py.Source
    $PythonPrefixArgs = @("-3")
} else {
    & $Python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is required." }
    $PythonCommand = $Python.Source
    $PythonPrefixArgs = @()
}

$SourceFull = [System.IO.Path]::GetFullPath($SourceRoot).TrimEnd('\')
$DestFull = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')
$NestedPrefix = $SourceFull + [System.IO.Path]::DirectorySeparatorChar
if ($DestFull.StartsWith($NestedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The install destination must not be inside the marketplace source directory."
}
if ($SourceFull -ne $DestFull) {
    $Stage = "$Destination.stage.$PID"
    $Old = "$Destination.old.$PID"
    Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $Old -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $Stage | Out-Null
    Get-ChildItem -LiteralPath $SourceRoot -Force |
        Where-Object { $_.Name -ne ".git" } |
        ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $Stage -Recurse -Force
        }
    Get-ChildItem -LiteralPath $Stage -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "__pycache__" } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $Stage -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    if (Test-Path $Destination) {
        try {
            Move-Item $Destination $Old -ErrorAction Stop
        } catch {
            $MoveFailure = $_.Exception.Message
            try {
                if (Test-Path $Old) {
                    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
                    Get-ChildItem -LiteralPath $Old -Force |
                        ForEach-Object {
                            Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
                        }
                    Remove-Item $Old -Recurse -Force
                }
                Remove-Item $Stage -Recurse -Force
            } catch {
                throw "Could not replace the active JAM installation and rollback was incomplete. Preserve '$Old' and restore it to '$Destination' after closing Codex. Move failure: $MoveFailure. Rollback failure: $($_.Exception.Message)"
            }
            throw "Could not replace the active JAM installation. The existing installation was restored. Close Codex Desktop and any JAM processes, then rerun the installer. Move failure: $MoveFailure"
        }
    }
    Move-Item $Stage $Destination
    Remove-Item $Old -Recurse -Force -ErrorAction SilentlyContinue
}

$McpArgs = @()
$McpArgs += $PythonPrefixArgs
$McpArgs += (Join-Path $PluginRoot "mcp\jam_mcp.py")
$McpConfig = @{
    mcpServers = @{
        jam_mode = @{
            command = $PythonCommand
            args = $McpArgs
            cwd = $PluginRoot
        }
    }
}
$McpJson = ($McpConfig | ConvertTo-Json -Depth 8) + [Environment]::NewLine
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $PluginRoot ".mcp.json"), $McpJson, $Utf8NoBom)

# Generate only JAM-prefixed custom agents. Campaign start/resume performs the
# live account-specific model catalog validation.
$RoutingCode = @'
from jam.routing import ensure_managed_agents, load_routing_config, requested_routing_from_config, resolve_routing
config = load_routing_config(create=True)
requested = requested_routing_from_config(config)
requested['validation'] = 'off'
resolved = resolve_routing(requested, catalog_entries=[])
ensure_managed_agents(resolved)
'@
$OldPythonPath = $env:PYTHONPATH
$OldCodexHome = $env:CODEX_HOME
try {
    $env:PYTHONPATH = $PluginRoot
    $env:CODEX_HOME = $CodexHome
    & $PythonCommand @PythonPrefixArgs -c $RoutingCode
    if ($LASTEXITCODE -ne 0) { throw "Could not generate JAM managed custom agents." }
} finally {
    $env:PYTHONPATH = $OldPythonPath
    $env:CODEX_HOME = $OldCodexHome
}

$MarketplaceManifest = Get-Content -LiteralPath (Join-Path $Destination ".agents\plugins\marketplace.json") -Raw |
    ConvertFrom-Json
$MarketName = $MarketplaceManifest.name
if (-not $MarketName) { throw "The marketplace manifest must declare a name." }

$PluginHelp = (& $Codex.Source plugin --help 2>&1 | Out-String)
$SupportsPluginInstall = $PluginHelp -match "(?m)^\s+add(?:\s|$)"

& $Codex.Source plugin marketplace add $Destination *> $null
if ($LASTEXITCODE -ne 0) { throw "Could not add the JAM local marketplace." }

[System.IO.File]::WriteAllText((Join-Path $Destination ".jam-marketplace-name"), $MarketName + [Environment]::NewLine, $Utf8NoBom)

if ($SupportsPluginInstall) {
    & $Codex.Source plugin add jam-mode -m $MarketName *> $null
    if ($LASTEXITCODE -ne 0) {
        & $Codex.Source plugin remove jam-mode -m $MarketName *> $null
        & $Codex.Source plugin add jam-mode -m $MarketName *> $null
        if ($LASTEXITCODE -ne 0) { throw "Could not install the JAM plugin from marketplace $MarketName." }
    }
}

New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
$JamCmd = Join-Path $BinDirectory "jam.cmd"
$Prefix = if ($PythonPrefixArgs.Count -gt 0) { " -3" } else { "" }
$JamCmdContent = @"
@echo off
set "PYTHONUTF8=1"
"$PythonCommand"$Prefix "$PluginRoot\scripts\jam.py" %*
"@
[System.IO.File]::WriteAllText($JamCmd, $JamCmdContent, $Utf8NoBom)

Write-Host ""
Write-Host "JAM Mode installed."
Write-Host "Marketplace: $MarketName"
Write-Host "Plugin source: $PluginRoot"
Write-Host "Companion command: $JamCmd"
Write-Host "State and routing config: $(Join-Path $CodexHome 'jam-mode')"
Write-Host "Managed agents: $(Join-Path $CodexHome 'agents\jam_*.toml')"
if (-not $SupportsPluginInstall) {
    Write-Host "Plugin activation: install or Refresh JAM Mode under Codex Settings > Plugins."
}
Write-Host ""
Write-Host "Restart Codex Desktop and start a new Desktop/CLI conversation before using the plugin."
Write-Host "Add $BinDirectory to PATH to call 'jam' from any terminal."
