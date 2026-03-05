#!/usr/bin/env pwsh
# =============================================================
# test_central_filters.ps1
# Testes automatizados para TODOS os filtros da Central de Ameaças
# =============================================================
$ErrorActionPreference = 'Stop'
$BASE = if ($env:API_BASE) { $env:API_BASE } else { "http://localhost:8000" }
$pass = 0; $fail = 0

function Test($name, $url, $check) {
    try {
        $r = Invoke-RestMethod -Uri "$BASE$url" -Method Get -TimeoutSec 15
        $ok = & $check $r
        if ($ok) { Write-Host "  [PASS] $name" -ForegroundColor Green; $script:pass++ }
        else     { Write-Host "  [FAIL] $name — check retornou false" -ForegroundColor Red; $script:fail++ }
    } catch {
        Write-Host "  [FAIL] $name — $($_.Exception.Message)" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "`n===== Central de Ameacas — Testes de Filtros =====`n" -ForegroundColor Cyan

# --- 1. Window default (2h) ---
Test "Window default = 2h" `
    "/api/batedor/central?window=2h&limit=5" `
    { param($r) $r.window -eq "2h" }

# --- 2. Window 3h retorna window=3h ---
Test "Window 3h retorna window=3h" `
    "/api/batedor/central?window=3h&limit=5" `
    { param($r) $r.window -eq "3h" }

# --- 3. Window 1h retorna window=1h ---
Test "Window 1h retorna window=1h" `
    "/api/batedor/central?window=1h&limit=5" `
    { param($r) $r.window -eq "1h" }

# --- 4. Window 30m retorna window=30m ---
Test "Window 30m retorna window=30m" `
    "/api/batedor/central?window=30m&limit=5" `
    { param($r) $r.window -eq "30m" }

# --- 5. Window 24h retorna window=24h ---
Test "Window 24h retorna window=24h" `
    "/api/batedor/central?window=24h&limit=5" `
    { param($r) $r.window -eq "24h" }

# --- 6. 3h tem total >= total de 1h (janela maior = mais dados) ---
$r1h = Invoke-RestMethod -Uri "$BASE/api/batedor/central?window=1h&limit=300" -Method Get -TimeoutSec 15
$r3h = Invoke-RestMethod -Uri "$BASE/api/batedor/central?window=3h&limit=300" -Method Get -TimeoutSec 15
if ($r3h.total -ge $r1h.total) {
    Write-Host "  [PASS] 3h.total ($($r3h.total)) >= 1h.total ($($r1h.total))" -ForegroundColor Green; $pass++
} else {
    Write-Host "  [FAIL] 3h.total ($($r3h.total)) < 1h.total ($($r1h.total))" -ForegroundColor Red; $fail++
}

# --- 7. Limit respeitado ---
Test "Limit=2 retorna no maximo 2 itens" `
    "/api/batedor/central?window=2h&limit=2" `
    { param($r) ($r.items).Count -le 2 }

# --- 8. grupos_comboio — window=3h retorna window=3h ---
Test "grupos_comboio window=3h" `
    "/api/batedor/grupos_comboio?window=3h&group_sizes=2&min_cameras=1" `
    { param($r) $r.window -eq "3h" }

# --- 9. grupos_comboio — group_sizes=3 aceito ---
Test "grupos_comboio group_sizes=3" `
    "/api/batedor/grupos_comboio?window=2h&group_sizes=3&min_cameras=1" `
    { param($r) $r.PSObject.Properties.Name -contains 'groups' }

# --- 10. grupos_comboio — group_sizes=2,3 aceito ---
Test "grupos_comboio group_sizes=2,3" `
    "/api/batedor/grupos_comboio?window=2h&group_sizes=2%2C3&min_cameras=1" `
    { param($r) $r.PSObject.Properties.Name -contains 'groups' }

# --- 11. grupos_comboio — order_mode=leader_front aceito ---
Test "grupos_comboio order_mode=leader_front" `
    "/api/batedor/grupos_comboio?window=2h&group_sizes=2&min_cameras=1&order_mode=leader_front" `
    { param($r) $r.PSObject.Properties.Name -contains 'groups' }

# --- 12. central — resposta contem campo 'items' e 'total' ---
Test "central retorna items e total" `
    "/api/batedor/central?window=2h&limit=5" `
    { param($r) ($r.PSObject.Properties.Name -contains 'items') -and ($r.PSObject.Properties.Name -contains 'total') }

# --- Resultado final ---
Write-Host "`n===== Resultado: $pass PASS / $fail FAIL =====" -ForegroundColor $(if ($fail -eq 0) { 'Green' } else { 'Red' })
exit $fail
