# Run backend tests against a disposable database. The application database is
# never used. Build the project first with .\eios\start.ps1 -Build.
[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$testContainer = "eios-intelligence-test-$([guid]::NewGuid().ToString('N').Substring(0,8))"
$testDsn = "postgresql://eios:eios@${testContainer}:5432/eios_test"
$mount = "type=bind,source=$root,target=/app,readonly"
$created = $false
try {
    docker run --rm -d --name $testContainer --network opentelemetry-demo `
        -e POSTGRES_USER=eios -e POSTGRES_PASSWORD=eios -e POSTGRES_DB=eios_test postgres:17-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Cannot start disposable database. Start the project first." }
    $created = $true
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker exec $testContainer pg_isready -U eios -d eios_test *>$null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Disposable database failed to become ready." }
    docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -e "EIOS_TEST_DSN=$testDsn" `
        --network opentelemetry-demo --mount $mount opentelemetry-demo-eios-intelligence `
        python -m unittest intelligence.tests.test_chat intelligence.tests.test_analytics intelligence.tests.test_collectors `
        intelligence.tests.test_ingestion intelligence.tests.test_store -v
    if ($LASTEXITCODE -ne 0) { throw "Analytics/storage tests failed." }
    docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app -e EIOS_API_TESTS=1 `
        -e "EIOS_TEST_DSN=$testDsn" -e "EIOS_POSTGRES_DSN=$testDsn" `
        --network opentelemetry-demo --mount $mount --workdir /app/orchestrator `
        opentelemetry-demo-eios-orchestrator python -m unittest intelligence.tests.test_api -v
    if ($LASTEXITCODE -ne 0) { throw "API tests failed." }
}
finally {
    if ($created) { docker stop $testContainer | Out-Null }
}
