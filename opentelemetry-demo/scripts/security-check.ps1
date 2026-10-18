#!/usr/bin/env pwsh
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
#
# security-check.ps1 — Pre-flight CIA-triad security audit for the OTel Demo stack.
# Usage:  .\scripts\security-check.ps1
# Exit code 1 if any HIGH severity finding is detected.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$HIGH   = 0
$MEDIUM = 0
$LOW    = 0
$findings = @()

function Add-Finding {
    param(
        [string]$Severity,
        [string]$Check,
        [string]$Detail
    )
    $findings += [PSCustomObject]@{ Severity = $Severity; Check = $Check; Detail = $Detail }
    switch ($Severity) {
        'HIGH'   { $script:HIGH++   }
        'MEDIUM' { $script:MEDIUM++ }
        'LOW'    { $script:LOW++    }
    }
}

Write-Host "`n══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  OTel Demo — Security Pre-flight Check" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════════`n" -ForegroundColor Cyan

# ─── 1. Hardcoded / weak secrets in .env files ───────────────────────────────
Write-Host "[1] Scanning .env files for weak secrets..." -ForegroundColor Yellow
$envFiles = Get-ChildItem -Path $PSScriptRoot\.. -Filter ".env*" -File -ErrorAction SilentlyContinue
foreach ($file in $envFiles) {
    $content = Get-Content $file.FullName -Raw

    $weakPatterns = @(
        @{ Pattern = '(?i)password\s*=\s*changeit';          Label = 'Default password "changeit"' }
        @{ Pattern = '(?i)password\s*=\s*password';          Label = 'Literal "password" as password' }
        @{ Pattern = '(?i)password\s*=\s*astronomy_password';Label = 'Demo astronomy_password' }
        @{ Pattern = '(?i)password\s*=\s*monitoring_password';Label = 'Demo monitoring_password' }
        @{ Pattern = 'SECRET_KEY_BASE\s*=\s*yYrEC';          Label = 'Default SECRET_KEY_BASE (demo value)' }
        @{ Pattern = '(?i)REPLACE_WITH';                      Label = 'Unfilled placeholder value' }
    )

    foreach ($p in $weakPatterns) {
        if ($content -match $p.Pattern) {
            Add-Finding -Severity 'HIGH' -Check ".env weak secret" `
                -Detail "$($p.Label) found in $($file.Name)"
        }
    }

    # Warn on any plaintext secret-like key set to a non-empty value
    $sensitiveKeys = $content | Select-String -Pattern '(?i)(password|secret|key|token)\s*=\s*\S+' -AllMatches
    foreach ($m in $sensitiveKeys.Matches) {
        $line = $m.Value
        # Exclude variable-reference values like ${VAR} and empty values
        if ($line -notmatch '\$\{' -and $line -notmatch '=$' -and $line -notmatch '=\s*$') {
            Add-Finding -Severity 'MEDIUM' -Check "Plaintext secret in env" `
                -Detail "$line (in $($file.Name)) — consider Docker Secrets"
        }
    }
}

# ─── 2. Containers running as root ────────────────────────────────────────────
Write-Host "[2] Checking containers running as root..." -ForegroundColor Yellow
try {
    $containers = docker ps --format '{{.Names}}' 2>$null
    foreach ($ctr in $containers) {
        $user = docker inspect --format '{{.Config.User}}' $ctr 2>$null
        if ([string]::IsNullOrWhiteSpace($user) -or $user -eq '0' -or $user -eq '0:0' -or $user -eq 'root') {
            Add-Finding -Severity 'HIGH' -Check "Root container" `
                -Detail "Container '$ctr' runs as root (user='$user')"
        }
    }
} catch {
    Add-Finding -Severity 'LOW' -Check "Docker unavailable" `
        -Detail "Could not connect to Docker daemon — skipping runtime checks"
}

# ─── 3. Exposed database ports ────────────────────────────────────────────────
Write-Host "[3] Checking exposed database ports..." -ForegroundColor Yellow
try {
    $dbPorts = @('5432', '6379', '9092')
    $portOutput = docker ps --format '{{.Names}} {{.Ports}}' 2>$null
    foreach ($line in $portOutput) {
        foreach ($port in $dbPorts) {
            if ($line -match "0\.0\.0\.0:$port->") {
                Add-Finding -Severity 'HIGH' -Check "Database port exposed" `
                    -Detail "Port $port bound to 0.0.0.0 on: $line"
            } elseif ($line -match "127\.0\.0\.1:$port->") {
                Add-Finding -Severity 'LOW' -Check "Database port on loopback" `
                    -Detail "Port $port on loopback (acceptable for local dev): $line"
            }
        }
    }
} catch {
    Add-Finding -Severity 'LOW' -Check "Port check skipped" -Detail "Docker unavailable"
}

# ─── 4. Containers without no-new-privileges ──────────────────────────────────
Write-Host "[4] Checking no-new-privileges security option..." -ForegroundColor Yellow
try {
    $containers = docker ps --format '{{.Names}}' 2>$null
    foreach ($ctr in $containers) {
        $secOpts = docker inspect --format '{{.HostConfig.SecurityOpt}}' $ctr 2>$null
        if ($secOpts -notmatch 'no-new-privileges') {
            Add-Finding -Severity 'MEDIUM' -Check "Missing no-new-privileges" `
                -Detail "Container '$ctr' lacks no-new-privileges:true"
        }
    }
} catch {
    Add-Finding -Severity 'LOW' -Check "SecurityOpt check skipped" -Detail "Docker unavailable"
}

# ─── 5. Envoy admin port publicly bound ────────────────────────────────────────
Write-Host "[5] Checking Envoy admin port (10000) exposure..." -ForegroundColor Yellow
try {
    $envoyPorts = docker ps --filter name=frontend-proxy --format '{{.Ports}}' 2>$null
    if ($envoyPorts -match '0\.0\.0\.0:10000->') {
        Add-Finding -Severity 'HIGH' -Check "Envoy admin exposed" `
            -Detail "Admin port 10000 bound to 0.0.0.0 — exposes metrics/config/drain endpoints"
    }
} catch {
    Add-Finding -Severity 'LOW' -Check "Envoy check skipped" -Detail "Docker unavailable"
}

# ─── 6. Compose overlay applied ────────────────────────────────────────────────
Write-Host "[6] Checking compose.security.yaml presence..." -ForegroundColor Yellow
$secOverlay = Join-Path $PSScriptRoot ".." "compose.security.yaml"
if (-not (Test-Path $secOverlay)) {
    Add-Finding -Severity 'HIGH' -Check "Security overlay missing" `
        -Detail "compose.security.yaml not found — hardening controls NOT applied"
} else {
    Write-Host "    compose.security.yaml present ✓" -ForegroundColor Green
}

# ─── 7. .env.security secrets still placeholder ────────────────────────────────
Write-Host "[7] Checking .env.security for placeholder values..." -ForegroundColor Yellow
$secEnv = Join-Path $PSScriptRoot ".." ".env.security"
if (Test-Path $secEnv) {
    $secContent = Get-Content $secEnv -Raw
    if ($secContent -match 'REPLACE_WITH') {
        Add-Finding -Severity 'HIGH' -Check "Unfilled .env.security placeholders" `
            -Detail ".env.security still contains REPLACE_WITH placeholder values — rotate ALL secrets before deploying"
    }
} else {
    Add-Finding -Severity 'MEDIUM' -Check ".env.security missing" `
        -Detail ".env.security not found — base .env weak passwords may be active"
}

# ─── 8. otel-collector user in compose files ──────────────────────────────────
Write-Host "[8] Checking otel-collector user config..." -ForegroundColor Yellow
$composeFile = Join-Path $PSScriptRoot ".." "compose.yaml"
if (Test-Path $composeFile) {
    $composeContent = Get-Content $composeFile -Raw
    if ($composeContent -match 'user:\s*0:0') {
        Add-Finding -Severity 'HIGH' -Check "otel-collector runs as root" `
            -Detail "compose.yaml sets user: 0:0 — apply compose.security.yaml to override to 65534:65534"
    }
}

# ─── Report ───────────────────────────────────────────────────────────────────
Write-Host "`n══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  FINDINGS SUMMARY" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════════════════" -ForegroundColor Cyan

$grouped = $findings | Group-Object -Property Severity | Sort-Object {
    switch ($_.Name) { 'HIGH' {0} 'MEDIUM' {1} 'LOW' {2} }
}

foreach ($group in $grouped) {
    $color = switch ($group.Name) {
        'HIGH'   { 'Red'    }
        'MEDIUM' { 'Yellow' }
        'LOW'    { 'Cyan'   }
    }
    Write-Host "`n  [$($group.Name)] ($($group.Count) findings)" -ForegroundColor $color
    foreach ($f in $group.Group) {
        Write-Host "    • [$($f.Check)] $($f.Detail)" -ForegroundColor $color
    }
}

Write-Host "`n──────────────────────────────────────────────────" -ForegroundColor Gray
Write-Host ("  HIGH: {0}   MEDIUM: {1}   LOW: {2}" -f $HIGH, $MEDIUM, $LOW)
Write-Host "──────────────────────────────────────────────────`n" -ForegroundColor Gray

if ($HIGH -gt 0) {
    Write-Host "✗ HIGH severity issues found. Resolve before deploying." -ForegroundColor Red
    exit 1
} elseif ($MEDIUM -gt 0) {
    Write-Host "⚠ MEDIUM severity issues found. Review recommended." -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "✓ No HIGH or MEDIUM issues detected." -ForegroundColor Green
    exit 0
}
