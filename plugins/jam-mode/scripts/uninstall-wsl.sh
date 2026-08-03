#!/usr/bin/env bash
set -euo pipefail
CODEX_HOME_EFFECTIVE="${CODEX_HOME:-$HOME/.codex}"
DEST_ROOT="${JAM_MARKETPLACE_HOME:-$CODEX_HOME_EFFECTIVE/jam-mode-marketplace}"
BIN_DIR="${JAM_BIN_DIR:-$HOME/.local/bin}"
MARKETPLACE_NAME="jam-mode-local"
if [[ -f "$DEST_ROOT/.jam-marketplace-name" ]]; then
  MARKETPLACE_NAME="$(head -n 1 "$DEST_ROOT/.jam-marketplace-name" | tr -d '\r\n')"
fi

if command -v codex >/dev/null 2>&1; then
  codex plugin remove jam-mode -m "$MARKETPLACE_NAME" --json >/dev/null 2>&1 || true
  codex plugin marketplace remove "$MARKETPLACE_NAME" --json >/dev/null 2>&1 || true
fi
if [[ -d "$DEST_ROOT/plugins/jam-mode" ]] && command -v python3 >/dev/null 2>&1; then
  CODEX_HOME="$CODEX_HOME_EFFECTIVE" PYTHONPATH="$DEST_ROOT/plugins/jam-mode" python3 - <<'PY' || true
from jam.routing import remove_managed_agents
remove_managed_agents()
PY
fi
rm -f "$BIN_DIR/jam"
rm -rf "$DEST_ROOT"
printf 'Removed the JAM plugin, marketplace source, and JAM-managed custom agents.\n'
printf 'Campaign history and routing config remain at %s/jam-mode; remove it manually only if you no longer need it.\n' "$CODEX_HOME_EFFECTIVE"
