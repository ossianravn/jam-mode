[CmdletBinding()]
param([string]$Destination, [string]$BinDirectory)
$ErrorActionPreference = "Stop"
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
if (-not $Destination) { $Destination = Join-Path $CodexHome "jam-mode-marketplace" }
if (-not $BinDirectory) { $BinDirectory = Join-Path $CodexHome "bin" }
$MarketplaceName = "jam-mode-local"
$MarketplaceNameFile = Join-Path $Destination ".jam-marketplace-name"
if (Test-Path $MarketplaceNameFile) {
    $SavedName = (Get-Content $MarketplaceNameFile -TotalCount 1).Trim()
    if ($SavedName) { $MarketplaceName = $SavedName }
}
$Codex = Get-Command codex -ErrorAction SilentlyContinue
if ($Codex) {
    & $Codex.Source plugin remove jam-mode -m $MarketplaceName --json *> $null
    & $Codex.Source plugin marketplace remove $MarketplaceName --json *> $null
}
$AgentsDirectory = Join-Path $CodexHome "agents"
if (Test-Path $AgentsDirectory) {
    Get-ChildItem -LiteralPath $AgentsDirectory -Filter "jam_*.toml" -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            $Text = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue
            if ($Text -and $Text.Contains("# JAM_MODE_MANAGED=1")) {
                Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
            }
        }
}
Remove-Item (Join-Path $BinDirectory "jam.cmd") -Force -ErrorAction SilentlyContinue
Remove-Item $Destination -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Removed the JAM plugin, marketplace source, and JAM-managed custom agents."
Write-Host "Campaign history and routing config remain at $(Join-Path $CodexHome 'jam-mode')."
