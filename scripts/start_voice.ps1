$ErrorActionPreference = 'Stop'
$trisProject = Split-Path -Parent $PSScriptRoot
if (Get-NetTCPConnection -LocalPort 7861 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host 'Voice server already listening on 7861; no process was stopped.'
    return
}
$trisSpeechPython = Join-Path $trisProject 'runtime\xtts\.venv\Scripts\python.exe'
$trisCudaPython = Join-Path $trisProject 'runtime\imagegen\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $trisSpeechPython)) { throw 'Speech runtime is not installed.' }
$trisVoicePython = $trisSpeechPython
if (Test-Path -LiteralPath $trisCudaPython) { $trisVoicePython = $trisCudaPython }
$env:PYTHONUTF8 = '1'
$trisVoiceLog = Join-Path $trisProject 'data'
New-Item -ItemType Directory -Path $trisVoiceLog -Force | Out-Null
$trisVoiceStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Start-Process -FilePath $trisVoicePython -ArgumentList @('-u','runtime\xtts\start_clone.py') -WorkingDirectory $trisProject -WindowStyle Hidden -RedirectStandardOutput (Join-Path $trisVoiceLog "voice-$trisVoiceStamp.log") -RedirectStandardError (Join-Path $trisVoiceLog "voice-$trisVoiceStamp.err.log") | Out-Null
