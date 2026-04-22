#!/usr/bin/env bash
# Install Memento OpenCode plugin.
# Usage: ./install-opencode-plugin.sh
#
# This script:
# 1. Creates ~/.config/opencode/plugins/memento/ directory
# 2. Copies plugin JS files there
# 3. Creates package.json for local plugin resolution
# 4. Installs @opencode-ai/plugin via bun
# 5. Adds "memento" to the plugin array in opencode.json
#
# OpenCode plugin loading order:
#   1. Global config (~/.config/opencode/opencode.json)
#   2. Project config (opencode.json)
#   3. Global plugins (~/.config/opencode/plugins/)
#   4. Project plugins (.opencode/plugins/)

set -euo pipefail

# Prerequisite: Bun is required (plugin uses Bun shell API and fetch with unix: sockets)
if ! command -v bun &>/dev/null; then
  echo "[memento] ERROR: Bun is required to run the OpenCode plugin" >&2
  echo "  Install: https://bun.sh/docs/installation" >&2
  exit 1
fi

PLUGIN_DIR="${HOME}/.config/opencode/plugins/memento"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMENTO_SRC="$(cd "$SCRIPT_DIR/../src/memento" && pwd)"

echo "[memento] Installing OpenCode plugin to $PLUGIN_DIR..."

mkdir -p "$PLUGIN_DIR"
mkdir -p "$PLUGIN_DIR/shared"

# Copy plugin files
cp "$MEMENTO_SRC/plugins/opencode/plugin.js" "$PLUGIN_DIR/"
cp "$MEMENTO_SRC/plugins/opencode/normalize.js" "$PLUGIN_DIR/"
cp "$MEMENTO_SRC/plugins/opencode/priming.js" "$PLUGIN_DIR/"
cp "$MEMENTO_SRC/plugins/shared/bridge.js" "$PLUGIN_DIR/shared/"

# Create package.json so OpenCode can resolve the "memento" plugin name
cat > "$PLUGIN_DIR/package.json" << 'EOF'
{
  "name": "memento",
  "version": "0.1.0",
  "type": "module",
  "main": "plugin.js",
  "exports": {
    ".": "./plugin.js"
  },
  "dependencies": {
    "@opencode-ai/plugin": ">=1.0.0"
  }
}
EOF

# Install dependencies via bun
cd "$PLUGIN_DIR"
bun install 2>/dev/null || true

# Update OpenCode config — try multiple config locations
for CONFIG_FILE in \
  "${HOME}/.config/opencode/opencode.json" \
  "${HOME}/.opencode.json"; do

  if [ -f "$CONFIG_FILE" ]; then
    if ! grep -q '"memento"' "$CONFIG_FILE" 2>/dev/null; then
      python3 -c "
import json
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
if 'plugin' not in cfg:
    cfg['plugin'] = []
if 'memento' not in cfg['plugin']:
    cfg['plugin'].append('memento')
if 'mcpServers' not in cfg:
    cfg['mcpServers'] = {}
if 'memento' not in cfg['mcpServers']:
    cfg['mcpServers']['memento'] = {
        'type': 'stdio',
        'command': 'memento-mcp-server',
        'args': []
    }
with open('$CONFIG_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
"
      echo "[memento] Updated $CONFIG_FILE"
    else
      echo "[memento] Plugin already registered in $CONFIG_FILE"
    fi
    break
  fi
done

# If no config exists, create one
if [ ! -f "${HOME}/.config/opencode/opencode.json" ] && [ ! -f "${HOME}/.opencode.json" ]; then
  mkdir -p "${HOME}/.config/opencode"
  cat > "${HOME}/.config/opencode/opencode.json" << 'CFGEOF'
{
  "plugin": ["memento"],
  "mcpServers": {
    "memento": {
      "type": "stdio",
      "command": "memento-mcp-server",
      "args": []
    }
  }
}
CFGEOF
  echo "[memento] Created ${HOME}/.config/opencode/opencode.json"
fi

echo ""
echo "[memento] OpenCode plugin installed successfully!"
echo ""
echo "Prerequisites:"
echo "  - Memento Python package installed (pip install -e .)"
echo "  - memento-worker CLI on PATH"
echo ""
echo "To verify:"
echo "  1. Run: memento status"
echo "  2. Open OpenCode in your project directory"
echo "  3. Check logs for [memento] messages"
