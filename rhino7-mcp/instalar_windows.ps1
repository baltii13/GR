# Instalador del MCP de Rhino 7 para Windows.
# Uso: clic derecho > "Ejecutar con PowerShell", o bien:
#   powershell -ExecutionPolicy Bypass -File instalar_windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverDir = Join-Path $root "server"
$listener = Join-Path $root "rhino_plugin\rhino_mcp_listener.py"

Write-Host "== 1/3 Instalando uv (si no esta) ==" -ForegroundColor Cyan
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
    $uv = Get-Command uv -ErrorAction Stop
}
$uvPath = $uv.Source
Write-Host "uv: $uvPath"

Write-Host "== 2/3 Instalando dependencias del servidor (descarga Python si hace falta) ==" -ForegroundColor Cyan
& $uvPath --directory $serverDir sync
if ($LASTEXITCODE -ne 0) { throw "uv sync ha fallado" }

Write-Host "== 3/3 Configurando Claude Desktop ==" -ForegroundColor Cyan
$cfgDir = Join-Path $env:APPDATA "Claude"
$cfgFile = Join-Path $cfgDir "claude_desktop_config.json"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
if (Test-Path $cfgFile) {
    Copy-Item $cfgFile "$cfgFile.bak" -Force
    $cfg = Get-Content $cfgFile -Raw | ConvertFrom-Json
} else {
    $cfg = New-Object PSObject
}
if (-not $cfg.PSObject.Properties["mcpServers"]) {
    $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object PSObject)
}
$entry = [PSCustomObject]@{ command = $uvPath; args = @("--directory", $serverDir, "run", "rhino-mcp") }
if ($cfg.mcpServers.PSObject.Properties["rhino"]) { $cfg.mcpServers.rhino = $entry }
else { $cfg.mcpServers | Add-Member -NotePropertyName rhino -NotePropertyValue $entry }
$json = $cfg | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($cfgFile, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Configuracion escrita en $cfgFile (copia de seguridad: .bak)"

if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Host "Claude Code detectado: registrando el MCP tambien alli"
    claude mcp remove rhino 2>$null | Out-Null
    claude mcp add rhino -- $uvPath --directory $serverDir run rhino-mcp
}

Write-Host ""
Write-Host "LISTO. Ultimos pasos:" -ForegroundColor Green
Write-Host " 1. Cierra Claude Desktop del todo (tambien desde la bandeja del sistema) y vuelve a abrirlo."
Write-Host " 2. En Rhino 7 escribe:  _-RunPythonScript `"$listener`""
Write-Host "    (Para que arranque solo: Herramientas > Opciones > General > Comandos al iniciar, pega esa misma linea.)"
Write-Host " 3. En Claude pide: 'Haz ping a Rhino'."
