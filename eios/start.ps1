# Start the EIOS stack from cold, including after a laptop restart.
#
#   .\eios\start.ps1            normal start
#   .\eios\start.ps1 -Demo      also raise the load generator to 20 users
#
# Handles the three things that bite on a cold boot:
#   1. Docker Desktop is not running yet.
#   2. Kafka's JVM outlives its healthcheck, so the first compose up reports
#      "dependency failed to start: container kafka is unhealthy" and stops.
#   3. checkout nil-panics on every order if it came up before Kafka was
#      serving, and never reconnects its producer on its own.

[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$Demo,
    [int]$DemoUsers = 20
)

$ErrorActionPreference = "Stop"

$demoDir = Join-Path $PSScriptRoot "..\opentelemetry-demo"
if (-not (Test-Path $demoDir)) {
    Write-Error "Cannot find opentelemetry-demo next to the eios directory."
}
$demoDir = (Resolve-Path $demoDir).Path

$composeArgs = @(
    "-f", "compose.yaml",
    "-f", "compose.full.yaml",
    "-f", "compose.observability.yaml",
    "-f", "../eios/compose.eios.yaml"
)

function Wait-For {
    param(
        [string]$Label,
        [scriptblock]$Test,
        [int]$TimeoutSeconds = 300
    )
    Write-Host "  waiting for $Label..." -NoNewline
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $ok = $false
        try { $ok = & $Test } catch { $ok = $false }
        if ($ok) { Write-Host " ok"; return $true }
        Start-Sleep -Seconds 5
        Write-Host "." -NoNewline
    }
    Write-Host " TIMED OUT"
    return $false
}

# --- 1. Docker daemon ------------------------------------------------------

Write-Host "`n[1/5] Docker" -ForegroundColor Cyan
docker info *>$null
if ($LASTEXITCODE -ne 0) {
    $userExe = "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
    $progExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $exe = if (Test-Path $userExe) { $userExe } elseif (Test-Path $progExe) { $progExe } else { $null }
    if ($exe) {
        Write-Host "  starting Docker Desktop ($exe)"
        Start-Process -FilePath $exe -WindowStyle Hidden
    } else {
        Write-Error "Docker is not running and Docker Desktop was not found at $userExe or $progExe"
    }
    if (-not (Wait-For "docker daemon" { docker info *>$null; $LASTEXITCODE -eq 0 } 420)) {
        Write-Error "Docker daemon did not come up."
    }
} else {
    Write-Host "  already running"
}

# --- 2. Bring the stack up -------------------------------------------------

Write-Host "`n[2/5] Compose up (first run pulls images)" -ForegroundColor Cyan
Push-Location $demoDir
try {
    if ($Build) {
        docker compose @composeArgs build eios-ingest eios-detect eios-orchestrator eios-intelligence eios-dashboard
        if ($LASTEXITCODE -ne 0) { Write-Error "Backend/dashboard build failed." }
    }
    # Kafka regularly misses its healthcheck window on a cold boot, which aborts
    # every service that depends on it. A second pass starts those once it is up.
    docker compose @composeArgs up -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  first pass incomplete (usually Kafka still starting) - retrying" -ForegroundColor Yellow
        Wait-For "kafka healthy" {
            (docker inspect --format '{{.State.Health.Status}}' kafka 2>$null) -eq "healthy"
        } 420 | Out-Null
        docker compose @composeArgs up -d
        if ($LASTEXITCODE -ne 0) { Write-Error "Compose still failing. Check: docker compose logs" }
    }

    # --- 3. Kafka actually serving, not merely 'healthy' -------------------
    # Note the broker advertises kafka:9092; probing localhost:9092 times out
    # even when the broker is fine.

    Write-Host "`n[3/5] Kafka broker" -ForegroundColor Cyan
    $brokerUp = Wait-For "broker accepting clients" {
        # Keep the probe JVM small and uninstrumented inside Kafka's memory limit.
        docker exec -e "KAFKA_HEAP_OPTS=-Xms32m -Xmx64m" -e "KAFKA_OPTS=" kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list *>$null
        $LASTEXITCODE -eq 0
    } 300

    # --- 4. Repair checkout if it lost its producer ------------------------

    Write-Host "`n[4/5] Order pipeline" -ForegroundColor Cyan
    if ($brokerUp) {
        $panicking = docker logs checkout --since 2m 2>&1 | Select-String -Pattern "sendToPostProcessor" -Quiet
        if ($panicking) {
            Write-Host "  checkout is panicking on publish - restarting it"
            docker restart checkout | Out-Null
        } else {
            Write-Host "  checkout healthy"
        }
    } else {
        Write-Host "  skipped: broker never came up" -ForegroundColor Yellow
    }

    # --- 5. Optional demo load --------------------------------------------

    Write-Host "`n[5/5] Load generator" -ForegroundColor Cyan
    if ($Demo) {
        # The default 5 users yields ~0.4 orders/min, under the detector's 1.0
        # floor, so rule:order_rate_drop cannot fire. 20 users gives ~3-7/min.
        Start-Sleep -Seconds 5
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:8080/loadgen/swarm" -Method Post `
                -Body @{ user_count = $DemoUsers; spawn_rate = 5 } -TimeoutSec 20 | Out-Null
            Write-Host "  raised to $DemoUsers users - let it run 10 min before injecting"
        } catch {
            Write-Host "  could not reach the loadgen UI yet; set it at 127.0.0.1:8080/loadgen/" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  left at the default 5 users (use -Demo before a demo run)"
    }
}
finally { Pop-Location }

# --- Summary ---------------------------------------------------------------

$bad = docker ps -a --filter "name=eios" --format "{{.Names}} {{.Status}}" |
       Where-Object { $_ -notmatch "Up " }
Write-Host "`n--- EIOS ---" -ForegroundColor Cyan
docker ps --filter "name=eios" --format "  {{.Names}}`t{{.Status}}"
if ($bad) { Write-Host "  NOT RUNNING: $bad" -ForegroundColor Red }

Write-Host @"

  Dashboard   http://127.0.0.1:5173
  Storefront  http://127.0.0.1:8080
  API         http://127.0.0.1:8000
  Jaeger      http://127.0.0.1:8080/jaeger/ui/
  Grafana     http://127.0.0.1:8080/grafana/
  Load gen    http://127.0.0.1:8080/loadgen/

  Use 127.0.0.1, not localhost - localhost resolves to IPv6 here and hangs.
"@ -ForegroundColor Gray
