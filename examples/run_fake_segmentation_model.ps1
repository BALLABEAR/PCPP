$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path "$PSScriptRoot\.."
$inputPath = "$PSScriptRoot\model_inputs\input.xyz"
$outputDir = "$PSScriptRoot\model_outputs"

if (!(Test-Path $outputDir)) {
    New-Item -Path $outputDir -ItemType Directory | Out-Null
}

Set-Location $projectRoot
python -m workers.segmentation.fake_segmentation.worker --input $inputPath --output-dir $outputDir

Write-Host "Done. Check output in $outputDir"
