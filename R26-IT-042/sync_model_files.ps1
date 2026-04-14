param(
    [Parameter(Mandatory = $true)]
    [string]$SourceModelDir,

    [Parameter(Mandatory = $false)]
    [string]$DestinationModelDir = (Join-Path $PSScriptRoot "C3_activity_monitoring\models")
)

$ErrorActionPreference = "Stop"

$requiredFiles = @(
    "user_behavioral_model.pkl",
    "feature_scaler.pkl",
    "ae_model.pkl",
    "ae_scaler.pkl",
    "ae_threshold.pkl",
    "ensemble_config.json"
)

if (-not (Test-Path $SourceModelDir)) {
    throw "Source model directory not found: $SourceModelDir"
}

New-Item -ItemType Directory -Force -Path $DestinationModelDir | Out-Null

Write-Host "Source      : $SourceModelDir"
Write-Host "Destination : $DestinationModelDir"
Write-Host ""

foreach ($fileName in $requiredFiles) {
    $sourcePath = Join-Path $SourceModelDir $fileName
    $destinationPath = Join-Path $DestinationModelDir $fileName

    if (-not (Test-Path $sourcePath)) {
        Write-Host "MISSING   : $fileName" -ForegroundColor Yellow
        continue
    }

    Copy-Item -Force -Path $sourcePath -Destination $destinationPath
    Write-Host "COPIED    : $fileName" -ForegroundColor Green
}

Write-Host ""
Write-Host "Verification:"
foreach ($fileName in $requiredFiles) {
    $destinationPath = Join-Path $DestinationModelDir $fileName
    if (Test-Path $destinationPath) {
        Write-Host "OK        : $fileName" -ForegroundColor Green
    } else {
        Write-Host "NOT FOUND : $fileName" -ForegroundColor Red
    }
}
