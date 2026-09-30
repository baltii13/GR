#!/usr/bin/env bash
# Instalador del MCP de Rhino 7 para macOS.
# Uso: abre Terminal en esta carpeta y ejecuta:  bash instalar_mac.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$ROOT/server"
LISTENER="$ROOT/rhino_plugin/rhino_mcp_listener.py"

echo "== 1/3 Instalando uv (si no esta) =="
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
UV="$(command -v uv)"
echo "uv: $UV"

echo "== 2/3 Instalando dependencias del servidor (descarga Python si hace falta) =="
"$UV" --directory "$SERVER_DIR" sync

echo "== 3/3 Configurando Claude Desktop =="
CFG_DIR="$HOME/Library/Application Support/Claude"
CFG="$CFG_DIR/claude_desktop_config.json"
mkdir -p "$CFG_DIR"
[ -f "$CFG" ] && cp "$CFG" "$CFG.bak"
"$UV" --directory "$SERVER_DIR" run python - "$CFG" "$UV" "$SERVER_DIR" <<'PY'
import json, os, sys
cfg_path, uv, server_dir = sys.argv[1:4]
cfg = {}
if os.path.exists(cfg_path) and os.path.getsize(cfg_path) > 0:
    with open(cfg_path) as f:
        cfg = json.load(f)
cfg.setdefault("mcpServers", {})["rhino"] = {
    "command": uv, "args": ["--directory", server_dir, "run", "rhino-mcp"]}
with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)
print("Configuracion escrita en", cfg_path, "(copia de seguridad: .bak)")
PY

if command -v claude >/dev/null 2>&1; then
    echo "Claude Code detectado: registrando el MCP tambien alli"
    claude mcp remove rhino >/dev/null 2>&1 || true
    claude mcp add rhino -- "$UV" --directory "$SERVER_DIR" run rhino-mcp
fi

echo
echo "LISTO. Ultimos pasos:"
echo " 1. Cierra Claude Desktop del todo (Cmd+Q) y vuelve a abrirlo."
echo " 2. En Rhino 7 escribe:  _-RunPythonScript \"$LISTENER\""
echo " 3. En Claude pide: 'Haz ping a Rhino'."
