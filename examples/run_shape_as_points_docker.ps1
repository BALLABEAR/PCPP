param(
    [string]$InputPath = "./examples/model_inputs/input.obj",
    [string]$OutputDir = "./examples/model_outputs",
    [string]$RepoPath = "./external_models/ShapeAsPoints",
    [string]$Config = "configs/optim_based/teaser.yaml",
    [int]$TotalEpochs = 200,
    [int]$GridRes = 128,
    [switch]$NoCuda
)

$ErrorActionPreference = "Stop"

$modelArgs = @("--repo-path", $RepoPath, "--config", $Config, "--total-epochs", "$TotalEpochs", "--grid-res", "$GridRes")
if ($NoCuda.IsPresent) { $modelArgs += "--no-cuda" }

& powershell -ExecutionPolicy Bypass -File "./examples/run_model_docker.ps1" `
  -TaskType "meshing" `
  -ModelId "shape_as_points" `
  -InputPath $InputPath `
  -OutputDir $OutputDir `
  -ModelArgs $modelArgs
