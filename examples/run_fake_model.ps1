$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path "$PSScriptRoot\.."
$inputPath = "$PSScriptRoot\sample_input.txt"
$outputDir = "$PSScriptRoot\out"

if (!(Test-Path $outputDir)) {
    New-Item -Path $outputDir -ItemType Directory | Out-Null
}

Set-Location $projectRoot
python -m workers.testing.sleep_worker.worker --input $inputPath --output-dir $outputDir

Write-Host "Done. Check output in $outputDir"
