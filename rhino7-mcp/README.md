# Rhino 7 MCP

Servidor [MCP](https://modelcontextprotocol.io) que permite a Claude (Claude Desktop, Claude Code u otro cliente MCP) controlar **Rhino 7**: inspeccionar el documento, crear y editar geometría, gestionar capas, ejecutar comandos y scripts, y capturar viewports para verificar el resultado.

## Arquitectura

Rhino 7 solo incorpora IronPython 2.7, así que el servidor MCP (Python 3.10+) no puede ejecutarse dentro de Rhino. Por eso hay dos partes que se comunican por un socket TCP local:

```
+-----------------+   stdio    +----------------------+   TCP 127.0.0.1:1999   +--------------------------+
| Claude Desktop  | <--------> |  rhino-mcp (server/) | <--------------------> |  rhino_mcp_listener.py   |
| / Claude Code   |  (MCP)     |  Python 3.10+, mcp   |  JSON delimitado por   |  IronPython 2.7 en Rhino |
+-----------------+            +----------------------+  saltos de línea       |  (hilo UI -> RhinoCommon)|
                                                                                +--------------------------+
```

- `rhino_plugin/rhino_mcp_listener.py`: script IronPython que se ejecuta dentro de Rhino. Abre un servidor TCP solo en localhost y ejecuta cada comando en el hilo de interfaz de Rhino.
- `server/`: paquete Python `rhino_mcp` (SDK oficial `mcp`, FastMCP) que expone las herramientas a Claude y las reenvía al listener.

Protocolo: una línea JSON por mensaje.
`{"id": "...", "command": "ping", "params": {}}` -> `{"id": "...", "status": "ok", "result": ...}` o `{"id": "...", "status": "error", "message": "..."}`.

## Requisitos

- Rhino 7 (Windows o macOS).
- Python 3.10 o superior en la máquina donde corre el cliente MCP.
- [`uv`](https://docs.astral.sh/uv/) (recomendado; gestiona Python y dependencias).
- Claude Desktop o Claude Code.

## Instalación rápida (automática)

1. Descomprime `rhino7-mcp.zip` en una carpeta fija (por ejemplo `C:\rhino7-mcp` o `~/rhino7-mcp`). No la muevas después: la configuración guarda esa ruta.
2. Ejecuta el instalador. Instala `uv` y las dependencias, y configura Claude Desktop (y Claude Code, si está instalado):
   - **Windows**: clic derecho en `instalar_windows.ps1` > *Ejecutar con PowerShell*.
   - **macOS**: en Terminal, dentro de la carpeta, `bash instalar_mac.sh`.
3. Reinicia Claude Desktop.
4. En Rhino 7 ejecuta `_-RunPythonScript "<carpeta>/rhino_plugin/rhino_mcp_listener.py"`. El instalador te muestra la línea exacta.
5. En Claude, pide: *"Haz ping a Rhino"*.

## Instalación paso a paso

### a) Instalar uv

- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

Reinicia la terminal y comprueba con `uv --version`.

### b) Arrancar el listener en Rhino

1. Abre Rhino 7.
2. Ejecuta el comando `_RunPythonScript` y selecciona `rhino7-mcp/rhino_plugin/rhino_mcp_listener.py`
   (o abre `_EditPythonScript`, carga el archivo y pulsa Run).
3. En la línea de comandos verás: `[rhino-mcp] Listener STARTED on 127.0.0.1:1999`.
4. Ejecutar el script otra vez **detiene** el listener (funciona como interruptor) y lo indica en pantalla.

Opcionales:

- **Alias**: `Tools > Options > Aliases`, crea un alias `MCP` con la macro
  `! _-RunPythonScript "C:\ruta\a\rhino7-mcp\rhino_plugin\rhino_mcp_listener.py"`
  (en macOS usa la ruta `/Users/.../rhino_mcp_listener.py`).
- **Botón de barra de herramientas**: arrastra un botón nuevo y usa la misma macro.
- **Arranque automático**: `Tools > Options > General > Command lists > Startup commands` (`Herramientas > Opciones > General > Lista de comandos`), añade:
  `_-RunPythonScript "C:\ruta\a\rhino7-mcp\rhino_plugin\rhino_mcp_listener.py"`
  Como el script es un interruptor, no lo pongas además en otra lista que se ejecute dos veces.

### c) Configurar el cliente MCP

**Claude Desktop**: edita `claude_desktop_config.json`

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "rhino": {
      "command": "uv",
      "args": ["--directory", "<ruta>/rhino7-mcp/server", "run", "rhino-mcp"]
    }
  }
}
```

Sustituye `<ruta>` por la ruta absoluta (en Windows usa `/` o `\\`, p. ej. `C:/Users/tu/GR/rhino7-mcp/server`). Reinicia Claude Desktop por completo. Si Claude Desktop no encuentra `uv`, usa la ruta absoluta del ejecutable en `command`.

**Claude Code**:

```bash
claude mcp add rhino -- uv --directory <ruta>/rhino7-mcp/server run rhino-mcp
```

Variables de entorno opcionales (añádelas en `env` del JSON o con `-e` en `claude mcp add`):

| Variable | Por defecto | Descripción |
|---|---|---|
| `RHINO_MCP_HOST` | `127.0.0.1` | Host del listener |
| `RHINO_MCP_PORT` | `1999` | Puerto del listener (debe coincidir con `PORT` en el script) |
| `RHINO_MCP_TIMEOUT` | `60` | Timeout en segundos por petición |

### d) Probar

Con el listener activo en Rhino, pide a Claude por ejemplo:

- "Comprueba la conexión con Rhino y dime las unidades del documento."
- "Crea una capa 'Muros' roja y dibuja en ella una caja de 5 x 0.2 x 3 en el origen."
- "Haz un cilindro de radio 0.5 y altura 3, réstalo de la caja y muéstrame una captura de la vista Perspective."
- "Lista los objetos de la capa 'Muros' y dime el volumen de cada uno."
- "Copia el objeto seleccionado 3 veces separado 2 unidades en X."

## Herramientas

| Herramienta | Descripción |
|---|---|
| `ping` | Comprueba la conexión y versiones |
| `get_document_info` | Archivo, unidades, tolerancia, nº de objetos, capas, bounding box |
| `get_objects` | Lista objetos con filtros (capa, tipo, nombre, solo seleccionados, límite) |
| `get_object_info` | Detalle de un objeto (geometría, longitud, área, volumen, user text) |
| `get_selected_objects` | Objetos seleccionados |
| `create_object` | Crea point, line, polyline, circle, arc, rectangle, box, sphere, cylinder, cone, surface_from_points, text |
| `delete_objects` | Elimina objetos |
| `transform_objects` | move, copy, rotate, scale, mirror |
| `set_object_attributes` | Nombre, capa, color, user text |
| `boolean_operation` | Unión, diferencia, intersección de sólidos |
| `list_layers` / `create_layer` / `set_current_layer` | Gestión de capas |
| `select_objects` | Selecciona objetos por id |
| `run_rhino_command` | Ejecuta un comando de Rhino (`RhinoApp.RunScript`) |
| `execute_python` | Ejecuta código IronPython 2.7 (`rs`, `sc`, `Rhino`, `System`, `doc`); devuelve lo impreso y la variable `result` |
| `capture_viewport` | Captura PNG de un viewport (tamaño y modo de visualización opcionales) |
| `zoom_extents` | Zoom a todo |
| `undo` | Deshace N pasos |

Además hay un prompt `rhino_modeling_workflow` con una guía breve de flujo de trabajo. Cada comando que modifica el documento queda como un único paso de deshacer (`Undo`).

## Solución de problemas

- **"Could not connect to Rhino ... run the listener script"**: el listener no está activo. Ejecútalo en Rhino (paso b). Recuerda que ejecutarlo otra vez lo detiene.
- **Puerto ocupado** (`Could not start listener ... port already in use`): otro proceso usa el 1999 (o una instancia de Rhino anterior). Cambia `PORT` al inicio del script y `RHINO_MCP_PORT` en el cliente, o cierra el otro proceso.
- **Firewall**: el tráfico es solo local (127.0.0.1); si un antivirus/firewall lo bloquea, permite a Rhino y a Python conexiones de loopback.
- **Timeout**: Rhino puede estar ocupado o mostrando un diálogo. Cierra los diálogos; sube `RHINO_MCP_TIMEOUT` para operaciones largas.
- **Versión de Python**: el servidor necesita Python 3.10+ (`uv` lo descarga solo). El listener es IronPython 2.7 y no se ejecuta con Python 3.
- **Claude Desktop no muestra las herramientas**: revisa el JSON, usa rutas absolutas, reinicia la aplicación y mira los logs de MCP (los mensajes del servidor van a stderr).
- **Un comando de `run_rhino_command` se queda esperando**: los comandos que piden entrada interactiva bloquean Rhino; usa la forma con guion (`_-Comando`) y todos sus argumentos.

## Seguridad

- `execute_python` y `run_rhino_command` ejecutan **código y comandos arbitrarios** con los permisos de tu usuario (acceso a archivos, red, etc.). Aprueba las llamadas con criterio y no expongas el puerto.
- El listener solo escucha en `127.0.0.1`; no lo cambies a `0.0.0.0`. No hay autenticación: cualquier proceso local puede enviarle comandos mientras esté activo. Detenlo cuando no lo uses.

## Desarrollo

```bash
cd server
uv sync --extra dev
uv run pytest
```

Los tests usan un listener falso (no necesitan Rhino). El listener se comprueba con `python3 -m py_compile rhino_plugin/rhino_mcp_listener.py`.
