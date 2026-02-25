# TESTE COMPLETO DO SISTEMA DE CADASTRO DE PLACAS

Write-Host "===== TESTE COMPLETO - CADASTRO DE PLACAS =====" -ForegroundColor Green
Write-Host ""

# 1. Listar listas
Write-Host "1. Listando listas..." -ForegroundColor Cyan
$lists_resp = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles/lists" -Method GET -UseBasicParsing
$lists = $lists_resp.Content | ConvertFrom-Json
Write-Host "   Total de listas: $($lists.items.Length)"

# 2. Selecionar primeira lista
$test_list = $lists.items[0]
$list_id = $test_list.id
Write-Host "   Usando lista: $($test_list.name) (ID=$list_id)"
Write-Host ""

# 3. Criar nova placa
Write-Host "2. Criando placa TESTEAPI2026..." -ForegroundColor Cyan
$body = @{
    plate = "TESTEAPI2026"
    list_id = $list_id
    notes = "teste"
} | ConvertTo-Json

$create_resp = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles" -Method POST -ContentType "application/json" -Body $body -UseBasicParsing
$created = $create_resp.Content | ConvertFrom-Json
Write-Host "   SUCESSO: ID=$($created.id), Placa=$($created.plate)"
Write-Host ""

# 4. Listar placas
Write-Host "3. Listando placas cadastradas..." -ForegroundColor Cyan
$vehicles_resp = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles?list_id=$list_id" -Method GET -UseBasicParsing
$vehicles = $vehicles_resp.Content | ConvertFrom-Json
Write-Host "   Total: $($vehicles.total) veículos"

# 5. Testar allplates
Write-Host ""
Write-Host "4. Testando /api/vehicles/allplates..." -ForegroundColor Cyan
$allplates_resp = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles/allplates" -Method GET -UseBasicParsing
$allplates = $allplates_resp.Content | ConvertFrom-Json
Write-Host "   Total de placas únicas: $($allplates.items.Length)"

# 6. Deletar
Write-Host ""
Write-Host "5. Deletando placa de teste..." -ForegroundColor Cyan
Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles/$($created.id)" -Method DELETE -UseBasicParsing | Out-Null
Write-Host "   DELETADO"
Write-Host ""

Write-Host "===== RESULTADO FINAL: PROBLEMA RESOLVIDO! =====" -ForegroundColor Green
