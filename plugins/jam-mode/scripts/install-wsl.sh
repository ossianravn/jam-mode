#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
CODEX_HOME_EFFECTIVE="${CODEX_HOME:-$HOME/.codex}"
DEST_ROOT="${JAM_MARKETPLACE_HOME:-$CODEX_HOME_EFFECTIVE/jam-mode-marketplace}"
PLUGIN_ROOT="$DEST_ROOT/plugins/jam-mode"
BIN_DIR="${JAM_BIN_DIR:-$HOME/.local/bin}"

fail() {
  printf 'JAM install: %s\n' "$*" >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || fail "python3 is required (3.10 or newer)."
python3 - <<'PY' || fail "Python 3.10 or newer is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
command -v codex >/dev/null 2>&1 || fail "the Codex CLI must be installed and available on PATH."

mkdir -p "$DEST_ROOT"
source_full="$(readlink -f "$SOURCE_ROOT")"
dest_full="$(readlink -f "$DEST_ROOT")"
if [[ "$dest_full" == "$source_full"/* ]]; then
  fail "the install destination must not be inside the marketplace source directory."
fi
if [[ "$source_full" != "$dest_full" ]]; then
  # Copy through a staging directory so an interrupted update cannot leave a
  # half-written marketplace. Preserve no state here; campaign state lives in
  # CODEX_HOME/jam-mode.
  STAGE="${DEST_ROOT}.stage.$$"
  rm -rf "$STAGE"
  mkdir -p "$STAGE"
  cp -a "$SOURCE_ROOT/." "$STAGE/"
  rm -rf "$STAGE/.git"
  find "$STAGE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$STAGE" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete 2>/dev/null || true
  OLD="${DEST_ROOT}.old.$$"
  rm -rf "$OLD"
  if [[ -n "$(find "$DEST_ROOT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    mv "$DEST_ROOT" "$OLD"
  else
    rmdir "$DEST_ROOT" 2>/dev/null || true
  fi
  mv "$STAGE" "$DEST_ROOT"
  rm -rf "$OLD"
fi

# Use an absolute launcher path. Local plugins are copied into a Codex cache;
# keeping the executable in the persistent marketplace source makes the cached
# .mcp.json independent of its working directory.
python3 - "$PLUGIN_ROOT" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
config = {
    "mcpServers": {
        "jam_mode": {
            "command": "python3",
            "args": [str(root / "mcp" / "jam_mcp.py")],
            "cwd": str(root),
        }
    }
}
(root / ".mcp.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY

# Materialize JAM-prefixed custom agents from the saved default routing policy.
# Campaign start/resume performs account-specific model/list validation; install
# deliberately avoids opening a live App Server session.
CODEX_HOME="$CODEX_HOME_EFFECTIVE" PYTHONPATH="$PLUGIN_ROOT" python3 - <<'PY'
from jam.routing import (
    ensure_managed_agents,
    load_routing_config,
    requested_routing_from_config,
    resolve_routing,
)
config = load_routing_config(create=True)
requested = requested_routing_from_config(config)
requested["validation"] = "off"
resolved = resolve_routing(requested, catalog_entries=[])
ensure_managed_agents(resolved)
PY

market_name="$(python3 - "$DEST_ROOT/.agents/plugins/marketplace.json" <<'PY'
import json
import sys
from pathlib import Path
name = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("name")
if not name:
    raise SystemExit("the marketplace manifest must declare a name")
print(name)
PY
)"
plugin_help="$(codex plugin --help 2>&1)"
if grep -Eq '^[[:space:]]+add([[:space:]]|$)' <<<"$plugin_help"; then
  supports_plugin_install=1
else
  supports_plugin_install=0
fi

codex plugin marketplace add "$DEST_ROOT" >/dev/null || fail "could not add the local marketplace."

printf '%s\n' "$market_name" > "$DEST_ROOT/.jam-marketplace-name"

if [[ "$supports_plugin_install" == 1 ]]; then
  if ! codex plugin add jam-mode -m "$market_name" >/dev/null 2>&1; then
    codex plugin remove jam-mode -m "$market_name" >/dev/null 2>&1 || true
    codex plugin add jam-mode -m "$market_name" >/dev/null
  fi
fi

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/jam" <<EOF
#!/usr/bin/env sh
exec python3 "${PLUGIN_ROOT}/scripts/jam.py" "\$@"
EOF
chmod +x "$BIN_DIR/jam"

printf '\nJAM Mode installed.\n'
printf 'Marketplace: %s\n' "$market_name"
printf 'Plugin source: %s\n' "$PLUGIN_ROOT"
printf 'Companion command: %s/jam\n' "$BIN_DIR"
printf 'State and routing config: %s/jam-mode\n' "$CODEX_HOME_EFFECTIVE"
printf 'Managed agents: %s/agents/jam_*.toml\n' "$CODEX_HOME_EFFECTIVE"
if [[ "$supports_plugin_install" == 0 ]]; then
  printf 'Plugin activation: install or Refresh JAM Mode under Codex Settings > Plugins.\n'
fi
printf '\nRestart Codex Desktop and start a new Desktop/CLI conversation before using the plugin.\n'
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  printf 'Add the companion command to PATH, for example:\n  export PATH="%s:$PATH"\n' "$BIN_DIR"
fi
if grep -qi microsoft /proc/version 2>/dev/null && [[ "$CODEX_HOME_EFFECTIVE" != /mnt/* ]]; then
  printf '\nWSL detected. To share this plugin, auth, and campaign state with Windows Desktop,\n'
  printf 'set CODEX_HOME to your Windows profile .codex directory before installing, e.g.:\n'
  printf '  export CODEX_HOME=/mnt/c/Users/<WindowsUser>/.codex\n'
fi
