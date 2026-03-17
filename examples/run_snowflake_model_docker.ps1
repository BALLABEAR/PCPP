param(
    [string]$InputPath = "./examples/model_inputs/input.xyz",
    [string]$WeightsPath = "./external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
    [string]$ConfigPath = "./external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
    [string]$OutputDir = "./examples/model_outputs",
    [string]$Device = "cuda",
    [string]$ImageTag = "pcpp-snowflake:gpu"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $InputPath)) { throw "Input file not found: $InputPath" }
if (!(Test-Path $WeightsPath)) { throw "Weights file not found: $WeightsPath" }
if (!(Test-Path $ConfigPath)) { throw "Config file not found: $ConfigPath" }
if (!(Test-Path $OutputDir)) { New-Item -Path $OutputDir -ItemType Directory | Out-Null }

$projectRoot = Resolve-Path "."

# Docker container runs Linux paths; normalize user paths.
$InputPath = $InputPath.Replace('\', '/')
$WeightsPath = $WeightsPath.Replace('\', '/')
$ConfigPath = $ConfigPath.Replace('\', '/')
$OutputDir = $OutputDir.Replace('\', '/')

docker build -t $ImageTag -f workers/completion/snowflake_net/Dockerfile .
if ($LASTEXITCODE -ne 0) { throw "Docker build failed with exit code $LASTEXITCODE" }

docker run --rm --gpus all `
  -v "${projectRoot}:/workspace" `
  -w /workspace `
  $ImageTag `
  python -m workers.completion.snowflake_net.worker `
    --input $InputPath `
    --output-dir $OutputDir `
    --mode model `
    --weights $WeightsPath `
    --config $ConfigPath `
    --device $Device

if ($LASTEXITCODE -ne 0) { throw "Docker run failed with exit code $LASTEXITCODE" }

Write-Host "Done. Output is in $OutputDir"
