Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$envFile = Join-Path (Join-Path $PSScriptRoot '..') '.env'

if (Test-Path $envFile) {
    Write-Error ".env already exists. Delete it first to regenerate."
    exit 1
}

function New-Key {
    param([int]$Bytes = 32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $b = [byte[]]::new($Bytes)
    $rng.GetBytes($b)
    return ($b | ForEach-Object { '{0:x2}' -f $_ }) -join ''
}

$pgPass  = New-Key -Bytes 32
$apiKey  = New-Key -Bytes 32

$content = @"
EIOS_POSTGRES_PASSWORD=$pgPass
EIOS_POSTGRES_USER=eios
EIOS_POSTGRES_DB=eios
EIOS_POSTGRES_DSN=postgresql://eios:$pgPass@eios-postgres:5432/eios
EIOS_API_KEY=$apiKey
EIOS_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
EIOS_LOG_LEVEL=INFO
EIOS_REDACTION_ENABLED=true
EIOS_AUDIT_INTEGRITY_ENABLED=true
EIOS_RATE_LIMIT_REQUESTS=200
EIOS_RATE_LIMIT_WINDOW=60
"@

Set-Content -Path $envFile -Value $content -Encoding UTF8
Write-Host "Generated .env successfully. NEVER commit this file." -ForegroundColor Green

$giPath = Join-Path (Join-Path $PSScriptRoot '..') '.gitignore'
if (Test-Path $giPath) {
    $gi = Get-Content $giPath -Raw
    if ($gi -notmatch '(?m)^\.env$') {
        Add-Content -Path $giPath -Value ([Environment]::NewLine + ".env")
        Write-Host "Added .env to .gitignore" -ForegroundColor Yellow
    }
}
