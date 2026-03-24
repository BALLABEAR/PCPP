# stage4_real_pipeline_run.ps1
# One-command check: upload -> run real DAG -> wait -> get download URLs
# Usage:
#   .\stage4_real_pipeline_run.ps1 -InputPath ".\data\benchmark_inputs\100k\room_scan1_100k.xyz"
# Optional:
#   -OrchestratorUrl "http://localhost:8000"
#   -PollSeconds 3
#   -TimeoutSeconds 7200

param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [string]$OrchestratorUrl = "http://localhost:8000",
    [int]$PollSeconds = 3,
    [int]$TimeoutSeconds = 7200,
    [int]$MeshingTotalEpochs = 200,
    [int]$MeshingGridRes = 128,
    [switch]$CpuOnly
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $InputPath)) {
    throw "Input file not found: $InputPath"
}

Write-Host "1) Uploading file: $InputPath"
$uploadRaw = & curl.exe -s -X POST "$OrchestratorUrl/files/upload" -F "file=@$InputPath"
if ($LASTEXITCODE -ne 0) { throw "Upload failed via curl.exe" }
$upload = $uploadRaw | ConvertFrom-Json

Write-Host "Uploaded to: $($upload.bucket)/$($upload.key)"

$flowParams = @{
    completion_mode = "model"
    completion_weights_path = "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth"
    completion_config_path = "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml"
    completion_device = "cuda"
    meshing_repo_path = "external_models/ShapeAsPoints"
    meshing_config_path = "configs/optim_based/teaser.yaml"
    meshing_total_epochs = $MeshingTotalEpochs
    meshing_grid_res = $MeshingGridRes
    meshing_no_cuda = $false
}

if ($CpuOnly.IsPresent) {
    Write-Host "CPU-only mode enabled (no CUDA)"
    $flowParams.completion_device = "cpu"
    $flowParams.meshing_no_cuda = $true
}

$payload = @{
    input_bucket = $upload.bucket
    input_key    = $upload.key
    flow_id      = "stage4_real_two_model_flow"
    flow_params  = $flowParams
} | ConvertTo-Json -Depth 10

Write-Host "2) Creating task (real DAG)..."
$task = Invoke-RestMethod -Method Post `
    -Uri "$OrchestratorUrl/tasks" `
    -ContentType "application/json" `
    -Body $payload

$taskId = $task.id
Write-Host "Task ID: $taskId"

Write-Host "3) Waiting for completion..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$status = $null
$pollCount = 0
$startedAt = Get-Date
$lastPrintedStatus = ""
$lastStatusChangedAt = $startedAt
$spinner = @("|", "/", "-", "\")

Write-Host ("Polling every {0}s (timeout: {1}s)..." -f $PollSeconds, $TimeoutSeconds)

do {
    Start-Sleep -Seconds $PollSeconds
    $pollCount++
    $status = Invoke-RestMethod -Method Get -Uri "$OrchestratorUrl/tasks/$taskId"

    $now = Get-Date
    $elapsed = New-TimeSpan -Start $startedAt -End $now
    $statusFor = New-TimeSpan -Start $lastStatusChangedAt -End $now

    if ($status.status -ne $lastPrintedStatus) {
        $lastPrintedStatus = $status.status
        $lastStatusChangedAt = $now
        $flowRunName = if ($status.flow_run_name) { $status.flow_run_name } else { "<not set yet>" }
        Write-Host ("[{0}] Status changed -> {1} | flow_run={2}" -f (Get-Date -Format "HH:mm:ss"), $status.status, $flowRunName)
    }
    else {
        $spin = $spinner[$pollCount % $spinner.Length]
        Write-Host ("[{0}] {1} still {2} | elapsed={3:mm\:ss} | unchanged_for={4:mm\:ss} | polls={5}" -f (Get-Date -Format "HH:mm:ss"), $spin, $status.status, $elapsed, $statusFor, $pollCount)
    }
} while (($status.status -eq "pending" -or $status.status -eq "running") -and (Get-Date) -lt $deadline)

if ($status.status -ne "completed") {
    Write-Host "Final task payload:"
    $status | ConvertTo-Json -Depth 10
    throw "Task did not complete successfully."
}

Write-Host "4) Getting final output URL..."
$resultUrlResp = Invoke-RestMethod -Method Get -Uri "$OrchestratorUrl/files/download" -Body @{} -ContentType "application/json" `
    -ErrorAction SilentlyContinue

# Use query params (GET style)
$resultUrlResp = Invoke-RestMethod -Method Get `
    -Uri "$OrchestratorUrl/files/download?bucket=$($status.result_bucket)&key=$([uri]::EscapeDataString($status.result_key))&expires_seconds=900"

$metricsKey = "results/$taskId/pipeline_metrics.json"
$metricsUrlResp = Invoke-RestMethod -Method Get `
    -Uri "$OrchestratorUrl/files/download?bucket=$($status.result_bucket)&key=$([uri]::EscapeDataString($metricsKey))&expires_seconds=900"

Write-Host ""
Write-Host "=== DONE ==="
Write-Host "Task ID:          $taskId"
Write-Host "Result bucket:    $($status.result_bucket)"
Write-Host "Result key:       $($status.result_key)"
Write-Host "Result URL:       $($resultUrlResp.url)"
Write-Host "Metrics key:      $metricsKey"
Write-Host "Metrics URL:      $($metricsUrlResp.url)"
Write-Host ""
Write-Host "Open Result URL to download final mesh (.ply)."
Write-Host "Open Metrics URL to inspect step timings (completion + meshing)."