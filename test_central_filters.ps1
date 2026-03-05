#!/usr/bin/env pwsh
# =============================================================
# test_central_filters.ps1
# Testes automatizados para TODOS os filtros da Central de Ameacas
# =============================================================
$ErrorActionPreference = 'Continue'
if ($env:API_BASE) { $BASE = $env:API_BASE } else { $BASE = 'http://localhost:8000' }
$pass = 0; $fail = 0

function Do-Test {
    param([string]$Name, [string]$Url, [scriptblock]$Check)
    try {
        $fullUrl = "$BASE$Url"
        $r = Invoke-RestMethod -Uri $fullUrl -Method Get -TimeoutSec 15
        $ok = (& $Check $r)
        if ($ok) {
            Write-Host "  [PASS] $Name" -ForegroundColor Green
            $script:pass++
        } else {
            Write-Host "  [FAIL] $Name - check retornou false" -ForegroundColor Red
            $script:fail++
        }
    } catch {
        Write-Host "  [FAIL] $Name - $($_.Exception.Message)" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host ""
Write-Host "===== Central de Ameacas - Testes de Filtros =====" -ForegroundColor Cyan
Write-Host ""

# --- 1. Window default (2h) ---
Do-Test -Name "Window default = 2h" `
    -Url '/api/batedor/central?window=2h&limit=5' `
    -Check { param($r) $r.window -eq '2h' }

# --- 2. Window 3h retorna window=3h ---
Do-Test -Name "Window 3h retorna window=3h" `
    -Url '/api/batedor/central?window=3h&limit=5' `
    -Check { param($r) $r.window -eq '3h' }

# --- 3. Window 1h retorna window=1h ---
Do-Test -Name "Window 1h retorna window=1h" `
    -Url '/api/batedor/central?window=1h&limit=5' `
    -Check { param($r) $r.window -eq '1h' }

# --- 4. Window 30m retorna window=30m ---
Do-Test -Name "Window 30m retorna window=30m" `
    -Url '/api/batedor/central?window=30m&limit=5' `
    -Check { param($r) $r.window -eq '30m' }

# --- 5. Window 24h retorna window=24h ---
Do-Test -Name "Window 24h retorna window=24h" `
    -Url '/api/batedor/central?window=24h&limit=5' `
    -Check { param($r) $r.window -eq '24h' }

# --- 6. 3h tem total >= total de 1h (janela maior = mais dados) ---
try {
    $r1h = Invoke-RestMethod -Uri "$BASE/api/batedor/central?window=1h&limit=300" -Method Get -TimeoutSec 15
    $r3h = Invoke-RestMethod -Uri "$BASE/api/batedor/central?window=3h&limit=300" -Method Get -TimeoutSec 15
    if ($r3h.total -ge $r1h.total) {
        Write-Host "  [PASS] 3h.total ($($r3h.total)) >= 1h.total ($($r1h.total))" -ForegroundColor Green
        $pass++
    } else {
        Write-Host "  [FAIL] 3h.total ($($r3h.total)) menor que 1h.total ($($r1h.total))" -ForegroundColor Red
        $fail++
    }
} catch {
    Write-Host "  [FAIL] Comparacao 3h vs 1h - $($_.Exception.Message)" -ForegroundColor Red
    $fail++
}

# --- 7. Limit respeitado ---
Do-Test -Name "Limit=2 retorna no maximo 2 itens" `
    -Url '/api/batedor/central?window=2h&limit=2' `
    -Check { param($r) @($r.items).Count -le 2 }

# --- 8. grupos_comboio - window=3h retorna window=3h ---
Do-Test -Name "grupos_comboio window=3h" `
    -Url '/api/batedor/grupos_comboio?window=3h&group_sizes=2&min_cameras=1' `
    -Check { param($r) $r.window -eq '3h' }

# --- 9. grupos_comboio - group_sizes=3 aceito ---
Do-Test -Name "grupos_comboio group_sizes=3" `
    -Url '/api/batedor/grupos_comboio?window=2h&group_sizes=3&min_cameras=1' `
    -Check { param($r) $null -ne $r.groups }

# --- 10. grupos_comboio - group_sizes=2,3 aceito ---
Do-Test -Name "grupos_comboio group_sizes=2,3" `
    -Url '/api/batedor/grupos_comboio?window=2h&group_sizes=2%2C3&min_cameras=1' `
    -Check { param($r) $null -ne $r.groups }

# --- 11. grupos_comboio - order_mode=leader_front aceito ---
Do-Test -Name "grupos_comboio order_mode=leader_front" `
    -Url '/api/batedor/grupos_comboio?window=2h&group_sizes=2&min_cameras=1&order_mode=leader_front' `
    -Check { param($r) $null -ne $r.groups }

# --- 12. central - resposta contem campo items e total ---
Do-Test -Name "central retorna items e total" `
    -Url '/api/batedor/central?window=2h&limit=5' `
    -Check { param($r) ($null -ne $r.items) -and ($null -ne $r.total) }

# --- Resultado final ---
Write-Host ""
if ($fail -eq 0) {
    Write-Host "===== Resultado: $pass PASS / $fail FAIL =====" -ForegroundColor Green
} else {
    Write-Host "===== Resultado: $pass PASS / $fail FAIL =====" -ForegroundColor Red
}
exit $fail
