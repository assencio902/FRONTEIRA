# Test POST /api/vehicles/lists
$body = @{
    name = "TESTE3"
    description = "Lista de teste via API"
    color = "#ffaa00"
    alarm_enabled = $true
    alarm_sound = "beep"
} | ConvertTo-Json

Write-Host "Criando nova lista..."
$response = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles/lists" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body `
    -UseBasicParsing

$data = $response.Content | ConvertFrom-Json
Write-Host "☑ Lista criada com sucesso!"
Write-Host "ID: $($data.id)"
Write-Host "Nome: $($data.name)"
Write-Host "Cor: $($data.color)"
Write-Host ""

# Test GET /api/vehicles/lists
Write-Host "Carregando todas as listas..."
$response = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles/lists" `
    -Method GET `
    -UseBasicParsing

$lists = $response.Content | ConvertFrom-Json
Write-Host "Total de listas: $($lists.items.Length)"
$lists.items | ForEach-Object {
    Write-Host "  - $($_.id): $($_.name) ($($_.vehicle_count) veículos)"
}
