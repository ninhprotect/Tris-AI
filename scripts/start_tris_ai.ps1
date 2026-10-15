param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$trisProject = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $trisProject
$trisPython = Join-Path $trisProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $trisPython)) { throw 'Missing project .venv.' }
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Build the UI first: scripts\build_workspace.ps1' }
# Process-scoped configuration: preserve the existing models and Windows settings.
foreach ($trisName in @('OLLAMA_MODELS','HF_HOME')) {
    $trisValue = [Environment]::GetEnvironmentVariable($trisName,'User')
    if ($trisValue) { [Environment]::SetEnvironmentVariable($trisName,$trisValue,'Process') }
}
if (-not $env:OLLAMA_MODELS -and (Test-Path -LiteralPath 'D:\TrisAI\ollama_models')) { $env:OLLAMA_MODELS = 'D:\TrisAI\ollama_models' }
if (-not $env:HF_HOME -and (Test-Path -LiteralPath 'D:\TrisAI\hf_home')) { $env:HF_HOME = 'D:\TrisAI\hf_home' }
$env:OLLAMA_FLASH_ATTENTION = '1'; $env:OLLAMA_KV_CACHE_TYPE = 'q8_0'
$env:OLLAMA_NUM_PARALLEL = '1'; $env:OLLAMA_MAX_LOADED_MODELS = '1'
# GTX 1060 (Pascal) runs on the CUDA 12 runner. The Vulkan path crashes on load and CUDA 13 has no Pascal kernels.
$env:OLLAMA_LLM_LIBRARY = 'cuda_v12'
$env:APP_OPEN_BROWSER = 'false'; $env:PYTHONUTF8 = '1'
$trisExisting = $null
try { $trisExisting = Invoke-RestMethod 'http://127.0.0.1:7860/v1/workspace/runtime' -TimeoutSec 3 } catch {}
if ($trisExisting.ui -eq 'tris-workspace') {
    # A live web port is not sufficient: force the backend to verify/repair its
    # Ollama runtime before reusing the existing Tris process.
    try { $trisExistingModels = Invoke-RestMethod 'http://127.0.0.1:7860/v1/workspace/models' -TimeoutSec 240 } catch { $trisExistingModels = $null }
    if (-not $trisExistingModels.models) {
        throw 'Tris AI is open but its local model is not ready. Close the existing Tris process and run this launcher again; no model will be downloaded or deleted.'
    }
    & (Join-Path $PSScriptRoot 'start_voice.ps1')
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:7860' }
    Write-Host 'Tris AI is already running at http://127.0.0.1:7860'
    exit 0
}
$trisBusy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(7860,8000) }
if ($trisBusy) { throw 'Port 7860 or 8000 is occupied by an older app. Stop that app before starting Tris AI. No process has been killed.' }
# A crashed or force-stopped Tris leaves its llama-server runner alive, still holding VRAM;
# the next start then fits only part of the model on the GPU. Only orphans of Tris's own
# Ollama folder (parent process gone) are stopped.
Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -like 'D:\TrisAI\Ollama\*' -and -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) } |
    ForEach-Object { Write-Host "Releasing VRAM held by an orphaned Ollama runner (pid $($_.ProcessId))."; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$trisOllamaCandidates = @(
    'D:\TrisAI\Ollama\ollama.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe')
)
$trisOllamaCommand = Get-Command ollama.exe -ErrorAction SilentlyContinue
if ($trisOllamaCommand) { $trisOllamaCandidates += $trisOllamaCommand.Source }
$trisOllama = $trisOllamaCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($trisOllama) { $env:PATH = (Split-Path -Parent $trisOllama) + ';' + $env:PATH }
try { $trisModels = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 } catch { $trisModels = $null }
if ($null -eq $trisModels) {
    if (-not $trisOllama) { throw 'Ollama executable not found.' }
    # Python starts and owns the local Ollama sidecar, then closes it with Tris.
    Write-Host 'Starting the recovered local Ollama runtime with Tris AI.'
}
if ($null -ne $trisModels -and -not $trisModels.models) {
    Write-Host 'Primary Ollama is using an empty/stale model store. Tris will attach its private loopback runtime to the verified model store; nothing is downloaded or deleted.' -ForegroundColor Yellow
}
$trisStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$trisLog = Join-Path $trisProject 'data'
New-Item -ItemType Directory -Path $trisLog -Force | Out-Null
& (Join-Path $PSScriptRoot 'start_voice.ps1')
$trisServer = Start-Process -FilePath $trisPython -ArgumentList @('-u','run_all.py') -WorkingDirectory $trisProject -WindowStyle Hidden -RedirectStandardOutput (Join-Path $trisLog "workspace-$trisStamp.log") -RedirectStandardError (Join-Path $trisLog "workspace-$trisStamp.err.log") -PassThru
# First cold load on older GPUs can take longer than one minute. The Python
# preflight has a 240-second bounded load timeout, so the launcher waits long
# enough for the same readiness contract instead of reporting a false timeout.
for ($trisTry=0; $trisTry -lt 300; $trisTry++) {
    Start-Sleep -Seconds 1
    if ($trisServer.HasExited) { throw "Tris AI stopped. Check data\workspace-$trisStamp.err.log" }
    try {
        $trisReady = Invoke-RestMethod 'http://127.0.0.1:7860/v1/workspace/runtime' -TimeoutSec 2
        if ($trisReady.ui -eq 'tris-workspace') {
            Write-Host 'Tris AI ready: http://127.0.0.1:7860 (shared API: 8000)'
            if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:7860' }
            exit 0
        }
    } catch {}
}
throw "Startup timed out. Check data\workspace-$trisStamp.err.log"
