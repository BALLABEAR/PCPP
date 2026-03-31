param(
    [string]$InputPath = "./examples/model_inputs/input.xyz",
    [string]$WeightsPath = "./external_models/PoinTr/pretrained/PoinTr_PCN.pth",
    [string]$ConfigPath = "cfgs/PCN_models/PoinTr.yaml",
    [string]$RepoPath = "./external_models/PoinTr",
    [string]$OutputDir = "./examples/model_outputs",
    [string]$Device = "cuda:0"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $InputPath)) { throw "Input file not found: $InputPath" }
if (!(Test-Path $WeightsPath)) { throw "Weights file not found: $WeightsPath" }
if (!(Test-Path $RepoPath)) { throw "Repo path not found: $RepoPath" }
if (!(Test-Path (Join-Path $RepoPath $ConfigPath))) { throw "Config file not found: $(Join-Path $RepoPath $ConfigPath)" }

# Normalize Windows-style paths before passing into Linux container.
$InputPath = $InputPath.Replace('\', '/')
$WeightsPath = $WeightsPath.Replace('\', '/')
$RepoPath = $RepoPath.Replace('\', '/')
$OutputDir = $OutputDir.Replace('\', '/')
$ConfigPath = $ConfigPath.Replace('\', '/')

$modelArgs = @(
    "--mode", "model",
    "--repo-path", $RepoPath,
    "--config", $ConfigPath,
    "--weights", $WeightsPath,
    "--device", $Device
)

$invokeArgs = @{
    TaskType = "completion"
    ModelId = "poin_tr"
    InputPath = $InputPath
    OutputDir = $OutputDir
    ModelArgs = $modelArgs
}

& "./examples/run_model_docker.ps1" @invokeArgs
