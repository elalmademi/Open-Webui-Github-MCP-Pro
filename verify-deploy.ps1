# verify-deploy.ps1 - Verificación Post-Deploy para PowerShell
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  VERIFICACIÓN POST-DEPLOY - GitHub MCP Server Pro v2.1      ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$MCP_URL = "http://localhost:8888"
$MCPO_URL = "http://localhost:8101"
$OPENWEBUI_URL = "http://localhost:8080"
$PASS = 0; $WARN = 0; $FAIL = 0

function Test-Endpoint {
    param($Url, $ExpectedStatus=200, $Description)
    try {
        $resp = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec 10 -ErrorAction Stop
        if ($resp.StatusCode -eq $ExpectedStatus) {
            Write-Host "✅ PASS: $Description ($Url) → HTTP $($resp.StatusCode)" -ForegroundColor Green
            $global:PASS++; return $resp.Content
        } else {
            Write-Host "❌ FAIL: $Description → HTTP $($resp.StatusCode) (esperado $ExpectedStatus)" -ForegroundColor Red
            $global:FAIL++; return $null
        }
    } catch {
        Write-Host "❌ FAIL: $Description → $_" -ForegroundColor Red
        $global:FAIL++; return $null
    }
}

# 1. Health MCP
$health = Test-Endpoint "$MCP_URL/health" 200 "MCP Health"
if ($health) {
    $h = $health | ConvertFrom-Json
    if ($h.status -eq "healthy") { Write-Host "  Status: healthy" -ForegroundColor Green; $global:PASS++ }
    else { Write-Host "  Status: $($h.status)" -ForegroundColor Yellow; $global:WARN++ }
    Write-Host "  Providers: $($h.providers_configured)"
    Write-Host "  GitHub: $($h.github)"
}

# 2. OpenAPI Schema
$openapi = Test-Endpoint "$MCP_URL/openapi.json" 200 "OpenAPI Schema"
if ($openapi) {
    $o = $openapi | ConvertFrom-Json
    $count = $o.paths.Count
    Write-Host "  Tools expuestas: $count" -ForegroundColor Green
    $global:PASS++
}

# 3. MCPO Bridge
$mcpo = Test-Endpoint "$MCPO_URL/health" 200 "MCPO Health"
if ($mcpo) { Write-Host "  MCPO Bridge OK" -ForegroundColor Green; $global:PASS++ }

# 4. Test LLM Real
Write-Host "`n--- Test LLM Broker ---"
try {
    $body = @{prompt="Responde solo: OK"; max_tokens=10} | ConvertTo-Json -Compress
    $llm = Invoke-WebRequest -Uri "$MCP_URL/tools/consultar_llm_externo" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 30 -ErrorAction Stop
    $result = $llm.Content | ConvertFrom-Json
    if ($result.response) {
        Write-Host "✅ LLM Broker funcional → Provider: $($result.provider), Fallback: $($result.fallback_used)" -ForegroundColor Green
        $global:PASS++
    } else { Write-Host "⚠️ LLM respondió sin contenido" -ForegroundColor Yellow; $global:WARN++ }
} catch { Write-Host "❌ LLM Broker falló: $_" -ForegroundColor Red; $global:FAIL++ }

# 5. Test GitHub Tools
Write-Host "`n--- Test GitHub Tools ---"
try {
    $body = @{query="microsoft/vscode stars:>10000"} | ConvertTo-Json -Compress
    $gh = Invoke-WebRequest -Uri "$MCP_URL/tools/buscar_repo" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 30 -ErrorAction Stop
    $result = $gh.Content | ConvertFrom-Json
    if ($result.result) {
        Write-Host "✅ GitHub Tools: $($result.result.Count) repos" -ForegroundColor Green
        $global:PASS++
    } else { Write-Host "⚠️ GitHub Tools: 0 resultados (¿GITHUB_TOKEN?)" -ForegroundColor Yellow; $global:WARN++ }
} catch { Write-Host "❌ GitHub Tools falló: $_" -ForegroundColor Red; $global:FAIL++ }

# 6. Volúmenes
Write-Host "`n--- Volúmenes ---"
try {
    $docs = docker exec mcp-github-server ls /app/local_docs 2>$null
    if ($LASTEXITCODE -eq 0) {
        $count = ($docs -split "`n").Count
        Write-Host "✅ local_docs montado: $count archivos" -ForegroundColor Green; $global:PASS++
    } else { Write-Host "⚠️ local_docs NO accesible" -ForegroundColor Yellow; $global:WARN++ }
} catch { Write-Host "⚠️ Error comprobando volúmenes" -ForegroundColor Yellow; $global:WARN++ }

# RESUMEN
Write-Host "`n╔══════════════════════════════════════════════════════════════╗"
Write-Host "║  RESUMEN:  PASS:$PASS  WARN:$WARN  FAIL:$FAIL"
Write-Host "╚══════════════════════════════════════════════════════════════╝"
if ($FAIL -gt 0) { exit 1 } elseif ($WARN -gt 0) { exit 2 } else { exit 0 }