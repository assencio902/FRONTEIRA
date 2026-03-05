# Script de Teste - Detecção de Comboio com Liderança
# ======================================================

$baseUrl = "http://localhost:8000"

Write-Host "`n╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  TESTE COMBOIO — Detecção com Liderança Consistente     ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# ────────────────────────────────────────────────────────────────
# TESTE 1: order_mode=any (comportamento padrão, qualquer ordem)
# ────────────────────────────────────────────────────────────────
Write-Host "=== TESTE 1: order_mode=any (padrão) — grupos de 2 ===" -ForegroundColor Yellow
try {
    $r1 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=24h&group_sizes=2&min_cameras=2&order_mode=any"
    Write-Host "  Total de grupos: $($r1.total)" -ForegroundColor Green
    Write-Host "  order_mode: $($r1.order_mode)" -ForegroundColor Gray
    Write-Host "  group_sizes: $($r1.group_sizes -join ',')" -ForegroundColor Gray
    if ($r1.groups.Count -gt 0) {
        $g = $r1.groups[0]
        Write-Host "  Primeiro grupo: $($g.plates -join ' + ')" -ForegroundColor White
        Write-Host "    Líder: $($g.leader) (ratio=$($g.leader_ratio))" -ForegroundColor Cyan
        Write-Host "    Câmeras: $($g.cameras_count)" -ForegroundColor Gray
        foreach ($ps in $g.plate_stats) {
            Write-Host "    ├─ $($ps.plate): front=$($ps.front_count) ratio=$($ps.front_ratio) role=$($ps.role)" -ForegroundColor DarkGray
        }
    }
} catch {
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# TESTE 2: order_mode=leader_front — grupo de 2 com líder fixo
# ────────────────────────────────────────────────────────────────
Write-Host "`n=== TESTE 2: order_mode=leader_front — grupo de 2 ===" -ForegroundColor Yellow
try {
    $r2 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=24h&group_sizes=2&min_cameras=2&order_mode=leader_front&leader_ratio=0.7"
    Write-Host "  Total de grupos com líder consistente: $($r2.total)" -ForegroundColor Green
    Write-Host "  leader_ratio_threshold: $($r2.leader_ratio_threshold)" -ForegroundColor Gray

    $allValid = $true
    foreach ($g in $r2.groups) {
        if ($g.leader_ratio -lt 0.7) {
            Write-Host "  FALHA: grupo $($g.plates -join ',') tem leader_ratio=$($g.leader_ratio) < 0.7" -ForegroundColor Red
            $allValid = $false
        }
    }
    if ($allValid -and $r2.groups.Count -gt 0) {
        Write-Host "  ✅ VALIDAÇÃO OK: Todos os $($r2.groups.Count) grupos têm líder >= 70%" -ForegroundColor Green
    }
    if ($r2.groups.Count -gt 0) {
        $eg = $r2.groups[0]
        Write-Host "  Exemplo: $($eg.plates -join ' + ')" -ForegroundColor White
        Write-Host "    Líder: $($eg.leader) (ratio=$($eg.leader_ratio))" -ForegroundColor Cyan
        foreach ($ps in $eg.plate_stats) {
            Write-Host "    ├─ $($ps.plate): role=$($ps.role) front=$($ps.front_count)/$($eg.cameras_count)" -ForegroundColor DarkGray
        }
    }
} catch {
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# TESTE 3: order_mode=leader_front — grupo de 3 com payload
# ────────────────────────────────────────────────────────────────
Write-Host "`n=== TESTE 3: order_mode=leader_front — grupo de 3 (payload) ===" -ForegroundColor Yellow
try {
    $r3 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=24h&group_sizes=3&min_cameras=2&order_mode=leader_front&leader_ratio=0.7&payload_max_front=0"
    Write-Host "  Total de grupos de 3 com líder+payload: $($r3.total)" -ForegroundColor Green

    $payloadOk = $true
    foreach ($g in $r3.groups) {
        $payload = $g.plate_stats | Where-Object { $_.role -eq 'payload' }
        if ($payload -and $payload.front_count -gt 0) {
            Write-Host "  FALHA: payload $($payload.plate) tem front_count=$($payload.front_count) > 0" -ForegroundColor Red
            $payloadOk = $false
        }
    }
    if ($payloadOk -and $r3.groups.Count -gt 0) {
        Write-Host "  ✅ VALIDAÇÃO OK: Todos os payloads têm front_count=0" -ForegroundColor Green
    }
    if ($r3.groups.Count -gt 0) {
        $eg = $r3.groups[0]
        Write-Host "  Exemplo: $($eg.plates -join ' + ')" -ForegroundColor White
        foreach ($ps in $eg.plate_stats) {
            $icon = switch ($ps.role) { 'leader' {'🏆'} 'payload' {'📦'} 'middle' {'🔹'} default {'·'} }
            Write-Host "    $icon $($ps.plate): role=$($ps.role) front=$($ps.front_count)/$($eg.cameras_count) ratio=$($ps.front_ratio)" -ForegroundColor DarkGray
        }
        Write-Host "    Camera details:" -ForegroundColor Gray
        foreach ($cam in $eg.camera_details[0..2]) {
            Write-Host "      📹 $($cam.cam_nome): 1º=$($cam.first_plate) ordem=[$($cam.plate_order -join '→')]" -ForegroundColor DarkCyan
        }
    }
} catch {
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# TESTE 4: group_sizes=2,3 (ambos tamanhos)
# ────────────────────────────────────────────────────────────────
Write-Host "`n=== TESTE 4: group_sizes=2,3 — todos os tamanhos ===" -ForegroundColor Yellow
try {
    $r4 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=24h&group_sizes=2,3&min_cameras=2&order_mode=leader_front&leader_ratio=0.7"
    Write-Host "  Total de grupos: $($r4.total)" -ForegroundColor Green
    $count2 = ($r4.groups | Where-Object { $_.group_size -eq 2 }).Count
    $count3 = ($r4.groups | Where-Object { $_.group_size -eq 3 }).Count
    Write-Host "  Grupos de 2: $count2" -ForegroundColor Gray
    Write-Host "  Grupos de 3: $count3" -ForegroundColor Gray
} catch {
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# TESTE 5: Validação de parâmetros não suportados
# ────────────────────────────────────────────────────────────────
Write-Host "`n=== TESTE 5: Parâmetro não suportado → HTTP 400 ===" -ForegroundColor Yellow
try {
    $err = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=2h&vehicle_type=car" -ErrorAction Stop
    Write-Host "  ❌ FALHA: deveria ter retornado erro HTTP 400" -ForegroundColor Red
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 400) {
        Write-Host "  ✅ HTTP 400: Parâmetro rejeitado corretamente" -ForegroundColor Green
        try { $body = $_.ErrorDetails.Message | ConvertFrom-Json; Write-Host "  Mensagem: $($body.detail)" -ForegroundColor Gray } catch {}
    } else {
        Write-Host "  ⚠️  Código inesperado: HTTP $code" -ForegroundColor Yellow
    }
}

# ────────────────────────────────────────────────────────────────
# TESTE 6: co_window clamped a 3600s
# ────────────────────────────────────────────────────────────────
Write-Host "`n=== TESTE 6: co_window=9999 → clamped a 3600s ===" -ForegroundColor Yellow
try {
    $r6 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=2h&co_window=9999&group_sizes=2"
    Write-Host "  co_window retornado: $($r6.co_window)s" -ForegroundColor Green
    if ($r6.co_window -eq 3600) {
        Write-Host "  ✅ Corretamente limitado a 3600s" -ForegroundColor Green
    } else {
        Write-Host "  ❌ Esperava 3600, recebeu $($r6.co_window)" -ForegroundColor Red
    }
} catch {
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
}

# ────────────────────────────────────────────────────────────────
# TESTE 7: Detalhe — plate_order por câmera
# ────────────────────────────────────────────────────────────────
Write-Host "`n=== TESTE 7: Detalhe de plate_order por câmera ===" -ForegroundColor Yellow
try {
    $r7 = Invoke-RestMethod -Uri "$baseUrl/api/batedor/grupos_comboio?window=24h&group_sizes=2,3&min_cameras=2&order_mode=any"
    if ($r7.groups.Count -gt 0) {
        $eg = $r7.groups[0]
        Write-Host "  Grupo: $($eg.plates -join ' + ') (líder=$($eg.leader))" -ForegroundColor White
        foreach ($cam in $eg.camera_details) {
            Write-Host "    📹 $($cam.cam_nome): [$($cam.plate_order -join ' → ')]  1º=$($cam.first_plate)" -ForegroundColor DarkCyan
        }
    } else {
        Write-Host "  Nenhum grupo encontrado para mostrar detalhes" -ForegroundColor DarkGray
    }
} catch {
    Write-Host "  ERRO: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  ✅ Todos os testes concluídos                          ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════╝`n" -ForegroundColor Green
