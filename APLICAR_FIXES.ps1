# ============================================================
# SCRIPT PARA APLICAR FIXES AL PROYECTO MCP REAL
# Ejecutar en PowerShell (Admin) desde CUALQUIER ubicación
# ============================================================

$Origen = "$env:USERPROFILE\Documents\IA\Workspace\mcp-fixes"
$Destino = "C:\openwebui-mcp-cloud\github-mcp-pro"

Write-Host "🔧 APLICANDO FIXES AL PROYECTO MCP PRO" -ForegroundColor Cyan
Write-Host "   Origen:  $Origen" -ForegroundColor Gray
Write-Host "   Destino: $Destino" -ForegroundColor Gray

if (-not (Test-Path $Origen)) {
    Write-Host "❌ No existe $Origen. Ejecuta primero la generación de archivos." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Destino)) {
    Write-Host "❌ No existe $Destino. Verifica la ruta del proyecto." -ForegroundColor Red
    exit 1
}

# Backup
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
Write-Host "`n📦 Creando backups..." -ForegroundColor Yellow
Copy-Item "$Destino\mcp-github-server\main.py" "$Destino\mcp-github-server\main.py.backup.$ts" -Force
Copy-Item "$Destino\docker-compose.local.yml" "$Destino\docker-compose.local.yml.backup.$ts" -Force
Copy-Item "$Destino\mcp-github-server\requirements.txt" "$Destino\mcp-github-server\requirements.txt.backup.$ts" -Force 2>$null
Copy-Item "$Destino\mcp-github-server\Dockerfile" "$Destino\mcp-github-server\Dockerfile.backup.$ts" -Force 2>$null
Write-Host "   ✅ Backups creados con timestamp $ts" -ForegroundColor Green

# Copiar archivos nuevos
Write-Host "`n📋 Copiando archivos corregidos..." -ForegroundColor Yellow
Copy-Item "$Origen\main.py" "$Destino\mcp-github-server\main.py" -Force
Write-Host "   ✅ main.py" -ForegroundColor Green
Copy-Item "$Origen\requirements.txt" "$Destino\mcp-github-server\requirements.txt" -Force
Write-Host "   ✅ requirements.txt" -ForegroundColor Green
Copy-Item "$Origen\Dockerfile" "$Destino\mcp-github-server\Dockerfile" -Force
Write-Host "   ✅ Dockerfile" -ForegroundColor Green
Copy-Item "$Origen\docker-compose.local.yml" "$Destino\docker-compose.local.yml" -Force
Write-Host "   ✅ docker-compose.local.yml" -ForegroundColor Green

# Rebuild
Write-Host "`n🧹 Limpieza total + Rebuild..." -ForegroundColor Cyan
cd $Destino
docker compose -f docker-compose.local.yml down -v --remove-orphans 2>$null
docker rmi $(docker images -q github-mcp-pro-mcp-github-server) 2>$null

Write-Host "`n🏗 Rebuilding..." -ForegroundColor Cyan
docker compose -f docker-compose.local.yml up -d --build

Write-Host "`n⏳ Esperando 20s..." -ForegroundColor Cyan
Start-Sleep 20

Write-Host "`n📋 VERIFICACIÓN FINAL:" -ForegroundColor Green
Write-Host "   Puerto:" -ForegroundColor Yellow
docker logs mcp-github-server 2>&1 | Select-String "Uvicorn running"

Write-Host "`n   Health:" -ForegroundColor Yellow
docker exec open-webui-dev curl -fsS http://mcp-github-server:8888/health 2>&1

Write-Host "`n   OpenAPI:" -ForegroundColor Yellow
$o = docker exec open-webui-dev curl -fsS http://mcp-github-server:8888/openapi.json 2>&1
if ($o -match "tools") { Write-Host "   ✅ OK" -ForegroundColor Green } else { Write-Host "   ❌ $o" -ForegroundColor Red }

Write-Host "`n   Tools test:" -ForegroundColor Yellow
docker exec open-webui-dev curl -fsS -X POST http://mcp-github-server:8888/tools/verificar_sistema -H "Content-Type: application/json" -d "{}" 2>&1
docker exec open-webui-dev curl -fsS -X POST http://mcp-github-server:8888/tools/leer_local -H "Content-Type: application/json" -d '{"nombre_archivo": "test.txt"}' 2>&1

Write-Host "`n🎯 CONFIGURA OPEN WEBUI:" -ForegroundColor Cyan
Write-Host '   URL: http://mcp-github-server:8888' -ForegroundColor Yellow