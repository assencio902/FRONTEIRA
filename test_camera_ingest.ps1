# ============================================================
# TEST_CAMERA_INGEST.PS1
# Testa a aceitacao de dados de camera pelo endpoint /api/simple-webhook
# Simula exatamente o que uma camera Hikvision envia (multipart + XML + imagem)
# ============================================================

param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$CameraIp = "172.21.151.16",
    [string]$Plate     = "TST0001",
    [int]   $Confidence = 95
)

$ErrorActionPreference = "Stop"

function Write-Ok($msg)   { Write-Host "[OK] $msg"   -ForegroundColor Green  }
function Write-Fail($msg) { Write-Host "[ERRO] $msg" -ForegroundColor Red    }
function Write-Info($msg) { Write-Host "[..] $msg"   -ForegroundColor Cyan   }
function Write-Title($msg){ Write-Host "`n===== $msg =====" -ForegroundColor Yellow }

# ============================================================
# 1. HEALTH CHECK
# ============================================================
Write-Title "1. HEALTH CHECK"
Write-Info "GET $BaseUrl/health"
try {
    $r = Invoke-WebRequest -Uri "$BaseUrl/health" -Method GET -UseBasicParsing
    $data = $r.Content | ConvertFrom-Json
    Write-Ok "Status: $($r.StatusCode) | $($r.Content)"
} catch {
    Write-Fail "Health check falhou: $($_.Exception.Message)"
    Write-Host "Verifique se o container esta rodando: docker ps" -ForegroundColor Yellow
    exit 1
}

# ============================================================
# 2. CATCH-ALL (teste simples sem XML)
# ============================================================
Write-Title "2. CATCH-ALL (qualquer camera, sem XML)"
Write-Info "POST $BaseUrl/api/catchall"
try {
    $body = '{"camera":"teste","plate":"ABC1234"}'
    $r = Invoke-WebRequest -Uri "$BaseUrl/api/catchall" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -UseBasicParsing
    $data = $r.Content | ConvertFrom-Json
    Write-Ok "Status: $($r.StatusCode) | method=$($data.method) | body_size=$($data.body_size) bytes"
} catch {
    Write-Fail "Catchall falhou: $($_.Exception.Message)"
}

# ============================================================
# 3. WEBHOOK SEM XML (corpo simples) - nao deve dar erro 500
# ============================================================
Write-Title "3. WEBHOOK SEM XML (corpo simples)"
Write-Info "POST $BaseUrl/api/simple-webhook  [Content-Type: text/plain]"
try {
    $r = Invoke-WebRequest -Uri "$BaseUrl/api/simple-webhook" `
        -Method POST `
        -ContentType "text/plain" `
        -Body "ping" `
        -UseBasicParsing
    Write-Ok "Status: $($r.StatusCode) | $($r.Content)"
} catch {
    Write-Fail "Esperado OK mas falhou: $($_.Exception.Message)"
}

# ============================================================
# 4. WEBHOOK COM XML HIKVISION (multipart) - formato real da camera
# ============================================================
Write-Title "4. WEBHOOK MULTIPART + XML HIKVISION (formato real da camera)"

# Monta o XML no formato exato que a camera envia
$xmlContent = @"
<?xml version="1.0" encoding="utf-8"?>
<EventNotificationAlert version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
<ipAddress>$CameraIp</ipAddress>
<ipv6Address>::</ipv6Address>
<protocol>HTTP</protocol>
<channelID>1</channelID>
<dateTime>$(Get-Date -Format "yyyy-MM-ddTHH:mm:ss.000-03:00")</dateTime>
<eventType>ANPR</eventType>
<eventState>active</eventState>
<eventDescription>ANPR</eventDescription>
<channelName>CAM_TESTE_PS1</channelName>
<deviceID>99</deviceID>
<ANPR>
<licensePlate>$Plate</licensePlate>
<direction>forward</direction>
<confidenceLevel>$Confidence</confidenceLevel>
<vehicleType>car</vehicleType>
</ANPR>
</EventNotificationAlert>
"@

# Gera imagem JPEG minima valida (>10KB exigido pelo endpoint)
# Cria um arquivo temporario com conteudo simulado
$xmlFile = [System.IO.Path]::GetTempFileName() + ".xml"
$imgFile = [System.IO.Path]::GetTempFileName() + ".jpg"

$xmlContent | Out-File -FilePath $xmlFile -Encoding utf8

# Imagem fake >= 10 KB (bytes JPEG header + padding)
$jpegHeader = [byte[]](0xFF,0xD8,0xFF,0xE0,0x00,0x10,0x4A,0x46,0x49,0x46,0x00)
$padding    = [byte[]](New-Object byte[] 15000)   # 15 KB de zeros
$imageBytes = $jpegHeader + $padding
[System.IO.File]::WriteAllBytes($imgFile, $imageBytes)

Write-Info "XML: $xmlFile ($([System.IO.File]::ReadAllBytes($xmlFile).Length) bytes)"
Write-Info "IMG: $imgFile ($([System.IO.File]::ReadAllBytes($imgFile).Length) bytes)"
Write-Info "POST $BaseUrl/api/simple-webhook  [multipart/form-data]"

try {
    # Monta multipart manualmente (PowerShell nativo nao suporta multipart facilmente)
    $boundary = "----BoundaryPS1$([System.Guid]::NewGuid().ToString('N'))"
    $CRLF = "`r`n"

    $xmlBytes = [System.IO.File]::ReadAllBytes($xmlFile)
    $imgBytes = [System.IO.File]::ReadAllBytes($imgFile)

    $ms = New-Object System.IO.MemoryStream

    # Parte 1: XML
    $part1Header = "--$boundary$CRLF" +
                   "Content-Disposition: form-data; name=`"XMLData`"; filename=`"event.xml`"$CRLF" +
                   "Content-Type: application/xml$CRLF$CRLF"
    $part1Bytes = [System.Text.Encoding]::UTF8.GetBytes($part1Header)
    $ms.Write($part1Bytes, 0, $part1Bytes.Length)
    $ms.Write($xmlBytes, 0, $xmlBytes.Length)

    $sep = [System.Text.Encoding]::UTF8.GetBytes($CRLF)
    $ms.Write($sep, 0, $sep.Length)

    # Parte 2: imagem
    $part2Header = "--$boundary$CRLF" +
                   "Content-Disposition: form-data; name=`"image`"; filename=`"plate.jpg`"$CRLF" +
                   "Content-Type: image/jpeg$CRLF$CRLF"
    $part2Bytes = [System.Text.Encoding]::UTF8.GetBytes($part2Header)
    $ms.Write($part2Bytes, 0, $part2Bytes.Length)
    $ms.Write($imgBytes, 0, $imgBytes.Length)

    # Final
    $finalBoundary = [System.Text.Encoding]::UTF8.GetBytes("$CRLF--$boundary--$CRLF")
    $ms.Write($finalBoundary, 0, $finalBoundary.Length)

    $bodyBytes = $ms.ToArray()

    $r = Invoke-WebRequest -Uri "$BaseUrl/api/simple-webhook" `
        -Method POST `
        -ContentType "multipart/form-data; boundary=$boundary" `
        -Body $bodyBytes `
        -UseBasicParsing

    $data = $r.Content | ConvertFrom-Json
    Write-Ok "Status: $($r.StatusCode)"
    Write-Ok "ok=$($data.ok) | placa=$($data.plate) | camera=$($data.camera_id) | canal=$($data.channel_name)"

    if ($data.ok -eq $true -and $data.plate -eq $Plate) {
        Write-Ok "PLACA RECONHECIDA CORRETAMENTE: $($data.plate)"
    } elseif ($data.ok -eq $false) {
        Write-Host "[AVISO] Camera provavelmente nao cadastrada no banco. Detalhes: $($data.detail)" -ForegroundColor Yellow
        Write-Host "        Cadastre a camera com IP '$CameraIp' no dashboard e tente novamente." -ForegroundColor Yellow
    }

} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Fail "HTTP $statusCode - $($_.Exception.Message)"
    if ($_.ErrorDetails.Message) {
        Write-Host "Resposta: $($_.ErrorDetails.Message)" -ForegroundColor Red
    }
} finally {
    Remove-Item $xmlFile -ErrorAction SilentlyContinue
    Remove-Item $imgFile -ErrorAction SilentlyContinue
}

# ============================================================
# 5. VERIFICA SE O EVENTO FOI SALVO NO BANCO
# ============================================================
Write-Title "5. VERIFICA EVENTO NO BANCO (ultimos 3 eventos)"
Write-Info "GET $BaseUrl/api/events?limit=3"
try {
    # Precisa de token JWT — usa login padrao
    $loginBody = '{"username":"admin","password":"admin123"}' 
    $loginResp  = Invoke-WebRequest -Uri "$BaseUrl/api/auth/login" `
        -Method POST `
        -ContentType "application/json" `
        -Body $loginBody `
        -UseBasicParsing
    $token = ($loginResp.Content | ConvertFrom-Json).access_token

    $r = Invoke-WebRequest -Uri "$BaseUrl/api/events?limit=3" `
        -Method GET `
        -Headers @{ Authorization = "Bearer $token" } `
        -UseBasicParsing
    $data = $r.Content | ConvertFrom-Json

    Write-Ok "Total de eventos no banco: $($data.total)"
    $data.items | ForEach-Object {
        $img = if ($_.image_path) { "com imagem" } else { "sem imagem" }
        Write-Host "   placa=$($_.plate) | camera=$($_.camera_id) | conf=$($_.confidence) | $img | $($_.occurred_at)" -ForegroundColor White
    }

    $found = $data.items | Where-Object { $_.plate -eq $Plate }
    if ($found) {
        Write-Ok "EVENTO DA PLACA '$Plate' ENCONTRADO NO BANCO!"
    } else {
        Write-Host "[AVISO] Placa '$Plate' nao aparece nos 3 ultimos eventos (pode estar mais abaixo ou camera nao cadastrada)" -ForegroundColor Yellow
    }

} catch {
    Write-Host "[AVISO] Nao foi possivel verificar eventos (login pode ter senha diferente): $($_.Exception.Message)" -ForegroundColor Yellow
}

# ============================================================
# RESUMO
# ============================================================
Write-Title "RESUMO DOS TESTES"
Write-Host @"

Endpoints testados:
  GET  /health                  - sistema online
  POST /api/catchall            - aceita qualquer dados
  POST /api/simple-webhook      - texto simples (sem XML)
  POST /api/simple-webhook      - multipart XML+imagem (formato Hikvision real)
  GET  /api/events              - conferencia no banco

Para testar com IP de camera diferente:
  .\test_camera_ingest.ps1 -CameraIp "192.168.1.50" -Plate "ABC1234"

Para testar contra servidor remoto:
  .\test_camera_ingest.ps1 -BaseUrl "http://SEU_IP:8000" -Plate "XYZ9999"

Lembre-se: a camera precisa estar CADASTRADA no dashboard para o
evento ser aceito (HTTP 403 caso contrario).
"@ -ForegroundColor Cyan
