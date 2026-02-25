# Test POST /api/vehicles - Adicionar placa à lista
$body = @{
    plate = "OHO7529"
    list_id = 4  # ID da lista "TEST"
    notes = "Veiculo teste"
} | ConvertTo-Json

Write-Host "Criando nova placa OHO7529 na lista TEST..."
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -UseBasicParsing

    $data = $response.Content | ConvertFrom-Json
    Write-Host "☑ Placa criada com sucesso!"
    Write-Host "ID: $($data.id)"
    Write-Host "Placa: $($data.plate)"
    Write-Host "Lista ID: $($data.list_id)"
    Write-Host ""
} catch {
    Write-Host "❌ ERRO: $($_.Exception.Message)"
}

# Listar todas as placas
Write-Host "Carregando todas as placas..."
$response = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles" `
    -Method GET `
    -UseBasicParsing

$data = $response.Content | ConvertFrom-Json
Write-Host "Total de placas: $($data.total)"
$data.items | ForEach-Object {
    Write-Host "  - $($_.plate) (Lista: $($_.list_name))"
}
