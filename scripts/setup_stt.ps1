param([switch]$Force)

$ErrorActionPreference = 'Stop'
$sttProject = Split-Path -Parent $PSScriptRoot
$sttPython = Join-Path $sttProject '.venv\Scripts\python.exe'
$sttModel = Join-Path $sttProject 'runtime\stt\models\small'
$sttCache = Join-Path $sttProject 'runtime\stt\cache'

if (-not (Test-Path -LiteralPath $sttPython)) {
    throw 'Missing project .venv. Create the Tris AI environment first.'
}

Write-Host 'Tris AI - local microphone transcription setup'
Write-Host "Model directory: $sttModel"

# Windows PowerShell 5.1 turns redirected native stderr into a terminating
# error under Stop preference; route the probe through cmd so 2>nul is cmd's.
$null = & cmd /c "`"$sttPython`" -c `"import faster_whisper`" 2>nul"
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing faster-whisper 1.2.1 into the project environment...'
    & $sttPython -m pip install 'faster-whisper==1.2.1'
    if ($LASTEXITCODE -ne 0) { throw 'Could not install faster-whisper.' }
}

$sttReady = (Test-Path -LiteralPath (Join-Path $sttModel 'config.json')) -and
            (Test-Path -LiteralPath (Join-Path $sttModel 'model.bin')) -and
            (Test-Path -LiteralPath (Join-Path $sttModel 'tokenizer.json'))
if ($Force -or -not $sttReady) {
    New-Item -ItemType Directory -Path $sttModel -Force | Out-Null
    New-Item -ItemType Directory -Path $sttCache -Force | Out-Null
    $env:TRIS_STT_SETUP_MODEL_DIR = $sttModel
    $env:TRIS_STT_SETUP_CACHE_DIR = $sttCache
    Write-Host 'Downloading the multilingual small model once (stored only on drive D)...'
    & $sttPython -c "import os; from faster_whisper.utils import download_model; print(download_model('small', output_dir=os.environ['TRIS_STT_SETUP_MODEL_DIR'], cache_dir=os.environ['TRIS_STT_SETUP_CACHE_DIR']))"
    if ($LASTEXITCODE -ne 0) { throw 'Could not download the local STT model.' }
}

$env:TRIS_STT_SETUP_MODEL_DIR = $sttModel
Write-Host 'Verifying that the local model can be loaded into RAM...'
& $sttPython -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['TRIS_STT_SETUP_MODEL_DIR'], device='cpu', compute_type='int8', cpu_threads=4, num_workers=1, local_files_only=True); print('Local STT ready.')"
if ($LASTEXITCODE -ne 0) { throw 'The STT model was downloaded but could not be loaded.' }

Write-Host 'Done. Restart Tris AI, allow Microphone for http://127.0.0.1:7860, then click the mic button.' -ForegroundColor Green
