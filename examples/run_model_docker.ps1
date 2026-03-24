param(
    [Parameter(Mandatory = $true)][string]$TaskType,
    [Parameter(Mandatory = $true)][string]$ModelId,
    [string]$InputPath = "./examples/model_inputs/input.xyz",
    [string]$OutputDir = "./examples/model_outputs",
    [string]$ImageTag = "",
    [string[]]$ModelArgs = @()
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $InputPath)) { throw "Input file not found: $InputPath" }
if (!(Test-Path $OutputDir)) { New-Item -Path $OutputDir -ItemType Directory | Out-Null }

$dockerfilePath = "workers/$TaskType/$ModelId/Dockerfile"
if (!(Test-Path $dockerfilePath)) { throw "Dockerfile not found: $dockerfilePath" }

# Build shared CUDA runtime once; model images inherit from it.
$runtimeImage = "pcpp-runtime-cuda118:latest"
$runtimeDockerfile = "workers/base/runtime/Dockerfile.cuda118"
$runtimeId = (docker images -q $runtimeImage 2>$null)
if ([string]::IsNullOrWhiteSpace($runtimeId)) {
    if (!(Test-Path $runtimeDockerfile)) { throw "Runtime Dockerfile not found: $runtimeDockerfile" }
    Write-Host "Building shared runtime image: $runtimeImage"
    docker build -t $runtimeImage -f $runtimeDockerfile .
    if ($LASTEXITCODE -ne 0) { throw "Runtime image build failed with exit code $LASTEXITCODE" }
}

if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = "pcpp-$TaskType-${ModelId}:gpu"
}

$projectRoot = Resolve-Path "."
$moduleName = "workers.$TaskType.$ModelId.worker"

# Docker container runs Linux paths; normalize user paths.
$InputPath = $InputPath.Replace('\', '/')
$OutputDir = $OutputDir.Replace('\', '/')

docker build -t $ImageTag -f $dockerfilePath .
if ($LASTEXITCODE -ne 0) { throw "Docker build failed with exit code $LASTEXITCODE" }

docker run --rm --gpus all `
  -v "${projectRoot}:/workspace" `
  -w /workspace `
  $ImageTag `
  python -m $moduleName `
    --input $InputPath `
    --output-dir $OutputDir `
    @ModelArgs

if ($LASTEXITCODE -ne 0) { throw "Docker run failed with exit code $LASTEXITCODE" }

Write-Host "Done. Output is in $OutputDir"
