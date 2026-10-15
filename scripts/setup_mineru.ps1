param(
    [string]$InstallRoot = "",
    [ValidateSet("pipeline", "all")]
    [string]$ModelSet = "pipeline"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path $projectRoot "runtime\mineru"
}
$absoluteRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$driveName = [System.IO.Path]::GetPathRoot($absoluteRoot).TrimEnd("\").TrimEnd(":")
$drive = Get-PSDrive -Name $driveName -PSProvider FileSystem
$minimumFree = 25GB
if ($drive.Free -lt $minimumFree) {
    $freeGB = [Math]::Round($drive.Free / 1GB, 1)
    throw "MinerU local cần tối thiểu 25 GB trống. Ổ $driveName hiện còn $freeGB GB. Hãy truyền -InstallRoot sang ổ khác."
}

$venvPath = Join-Path $absoluteRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$mineruPath = Join-Path $venvPath "Scripts\mineru.exe"

New-Item -ItemType Directory -Path $absoluteRoot -Force | Out-Null
python -m venv $venvPath
& $pythonPath -m pip install --upgrade pip
& $pythonPath -m pip install "mineru[core]"
& $pythonPath -m mineru.cli.models_download -s huggingface -m $ModelSet

[Environment]::SetEnvironmentVariable("MINERU_EXECUTABLE", $mineruPath, "User")
[Environment]::SetEnvironmentVariable("MINERU_BACKEND", "pipeline", "User")
Write-Host "MinerU đã cài tại $absoluteRoot"
Write-Host "Hãy khởi động lại Tris AI để nhận biến môi trường mới."
