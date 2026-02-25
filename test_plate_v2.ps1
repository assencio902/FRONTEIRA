# First, list all lists to get the correct ID
Write-Host "Getting all lists..."
$lists_response = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles/lists" `
    -Method GET `
    -UseBasicParsing
$lists = $lists_response.Content | ConvertFrom-Json
Write-Host "Available lists:"
$lists.items | ForEach-Object {
    Write-Host "  ID: $($_.id), Name: $($_.name)"
}

# Get the ID of "TEST" list
$test_list = $lists.items | Where-Object { $_.name -eq "TEST" }
if ($test_list) {
    $list_id = $test_list.id
    Write-Host ""
    Write-Host "Using list ID: $list_id for TEST list"
    Write-Host ""
    
    # Now try to add a plate
    $body = @{
        plate = "XYZ9999"
        list_id = $list_id
        notes = "Test vehicle"
    } | ConvertTo-Json
    
    Write-Host "Attempting to add plate XYZ9999..."
    Write-Host "Body: $body"
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/vehicles" `
            -Method POST `
            -ContentType "application/json" `
            -Body $body `
            -UseBasicParsing
        
        $data = $response.Content | ConvertFrom-Json
        Write-Host "SUCCESS: Plate created!"
        Write-Host ($data | ConvertTo-Json)
    } catch {
        Write-Host "ERROR: $($_.Exception.Message)"
    }
} else {
    Write-Host "TEST list not found!"
}
