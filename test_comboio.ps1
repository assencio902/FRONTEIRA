# Script de Teste - Detecção de Comboio (Sistema Limpo)
# ========================================================

$baseUrl = "http://localhost:8000"

Write-Host "`n=== TESTE 1: Comboios em 2+ câmeras (últimas 2h) ===" -ForegroundColor Cyan
$response1 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=2h&min_cameras=2&min_vehicles=2"
Write-Host "Total de grupos encontrados: $($response1.total)" -ForegroundColor Green
Write-Host "Parâmetros: window=$($response1.window), co_window=$($response1.co_window)s, min_cameras=$($response1.min_cameras), min_passes=$($response1.min_passes)"
if ($response1.groups.Count -gt 0) {
    Write-Host "`nPrimeiros resultados:" -ForegroundColor Yellow
    foreach ($group in $response1.groups[0..2]) {
        Write-Host "  - Placas: $($group.plates -join ', ')" -ForegroundColor White
        Write-Host "    Câmeras: $($group.cameras_count) [$($group.cameras -join ', ')]" -ForegroundColor Gray
        Write-Host "    Passes: $($group.passes) vezes" -ForegroundColor Gray
        Write-Host "    Período: $($group.first_seen) → $($group.last_seen)" -ForegroundColor Gray
        Write-Host ""
    }
} else {
    Write-Host "  Nenhum grupo encontrado" -ForegroundColor DarkGray
}

Write-Host "`n=== TESTE 2: Janela máxima (co_window=3600s = 1 hora) ===" -ForegroundColor Cyan
$response2 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=24h&co_window=3600&min_vehicles=3&min_cameras=2"
Write-Host "Total de grupos (3 veículos): $($response2.total)" -ForegroundColor Green
Write-Host "co_window aplicado: $($response2.co_window)s (deve ser 3600)" -ForegroundColor Gray
if ($response2.groups.Count -gt 0) {
    Write-Host "`nMaior grupo:" -ForegroundColor Yellow
    $biggest = $response2.groups | Sort-Object -Property group_size -Descending | Select-Object -First 1
    Write-Host "  - $($biggest.group_size) veículos: $($biggest.plates -join ', ')" -ForegroundColor White
    Write-Host "    Visto em $($biggest.cameras_count) câmeras" -ForegroundColor Gray
    Write-Host "    Span temporal: $($biggest.total_span_sec)s" -ForegroundColor Gray
} else {
    Write-Host "  Nenhum grupo grande encontrado" -ForegroundColor DarkGray
}

Write-Host "`n=== TESTE 3: Filtro min_passes (repetições) ===" -ForegroundColor Cyan
$response3 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=12h&min_vehicles=2&min_cameras=3&min_passes=3"
Write-Host "Grupos vistos 3+ vezes: $($response3.total)" -ForegroundColor Green
Write-Host "min_passes aplicado: $($response3.min_passes)" -ForegroundColor Gray

Write-Host "`n=== TESTE 4: Validação de parâmetros não suportados ===" -ForegroundColor Cyan
try {
    $errorResponse = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=2h&direcao=norte&min_cameras=2" -ErrorAction Stop
    Write-Host "  ❌ FALHA: deveria ter retornado erro HTTP 400" -ForegroundColor Red
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 400) {
        Write-Host "  ✅ SUCESSO: Retornou HTTP 400 (Bad Request)" -ForegroundColor Green
        $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "  Mensagem: $($errorBody.detail)" -ForegroundColor Gray
    } else {
        Write-Host "  ⚠️  Erro inesperado: HTTP $statusCode" -ForegroundColor Yellow
    }
}

Write-Host "`n=== TESTE 5: Limite de co_window (tenta > 3600s) ===" -ForegroundColor Cyan
$response5 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=2h&co_window=7200&min_cameras=1"
Write-Host "co_window solicitado: 7200s (2 horas)" -ForegroundColor Gray
Write-Host "co_window aplicado: $($response5.co_window)s (deve ser 3600, máximo)" -ForegroundColor Green

Write-Host "`n=== TESTE 6: Detalhes de câmeras ===" -ForegroundColor Cyan
if ($response1.groups.Count -gt 0) {
    $example = $response1.groups[0]
    Write-Host "Exemplo de grupo com detalhes por câmera:" -ForegroundColor Yellow
    Write-Host "Placas: $($example.plates -join ', ')" -ForegroundColor White
    Write-Host "`nDetalhes por câmera:" -ForegroundColor Gray
    foreach ($cam in $example.camera_details) {
        Write-Host "  📹 $($cam.cam_nome)" -ForegroundColor Cyan
        Write-Host "     Primeira detecção: $($cam.first_seen)" -ForegroundColor DarkGray
        Write-Host "     Última detecção:   $($cam.last_seen)" -ForegroundColor DarkGray
        Write-Host "     Span na câmera:    $($cam.span_sec)s" -ForegroundColor DarkGray
        Write-Host ""
    }
}

Write-Host "`n✅ Testes concluídos!`n" -ForegroundColor Green
