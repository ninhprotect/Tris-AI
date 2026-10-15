param(
    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path $projectRoot "runtime\imagegen"
}
$absoluteRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$driveName = [System.IO.Path]::GetPathRoot($absoluteRoot).TrimEnd("\").TrimEnd(":")
$drive = Get-PSDrive -Name $driveName -PSProvider FileSystem
$minimumFree = 15GB
if ($drive.Free -lt $minimumFree) {
    $freeGB = [Math]::Round($drive.Free / 1GB, 1)
    throw "Bộ tạo ảnh local cần tối thiểu 15 GB trống. Ổ $driveName hiện còn $freeGB GB."
}

$venvPath = Join-Path $absoluteRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

New-Item -ItemType Directory -Path $absoluteRoot -Force | Out-Null
python -m venv $venvPath
& $pythonPath -m pip install --upgrade pip

# CUDA build of torch for the GTX 10-series GPU; falls back to CPU elsewhere.
& $pythonPath -m pip install torch==2.5.1 torchvision --index-url https://download.pytorch.org/whl/cu121
& $pythonPath -m pip install diffusers transformers accelerate safetensors imageio imageio-ffmpeg

# Pre-download sd-turbo so the first generation does not stall on network.
& $pythonPath -c "from huggingface_hub import snapshot_download; snapshot_download('stabilityai/sd-turbo')"

Write-Host "Bộ tạo ảnh/GIF/video local đã cài tại $absoluteRoot"
Write-Host "Khởi động lại Tris AI để sử dụng."
