param([switch]$Install)
$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path -Parent $PSScriptRoot
$workspaceNodeCommand = Get-Command node -ErrorAction SilentlyContinue
$workspaceRuntime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node'
$workspaceNode = if ($workspaceNodeCommand) { $workspaceNodeCommand.Source } else { Join-Path $workspaceRuntime 'bin\node.exe' }
if (-not (Test-Path -LiteralPath $workspaceNode)) { throw 'Install Node.js 22.12+ or Node.js 24, then reopen PowerShell.' }
$workspacePnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
$workspacePnpm = Join-Path $workspaceRuntime 'node_modules\pnpm\bin\pnpm.cjs'
$workspaceOriginalPath = $env:PATH
try {
    $env:PATH = (Split-Path -Parent $workspaceNode) + ';' + $env:PATH
    Push-Location (Join-Path $workspaceRoot 'frontend')
    if ($Install -or -not (Test-Path -LiteralPath 'node_modules')) {
        if ($workspacePnpmCommand) { & $workspacePnpmCommand.Source install --frozen-lockfile }
        elseif (Test-Path -LiteralPath $workspacePnpm) { & $workspaceNode $workspacePnpm install --frozen-lockfile }
        else { throw 'Install pnpm 11, then rerun this script with -Install.' }
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    }
    & $workspaceNode 'node_modules\typescript\bin\tsc' -b
    if ($LASTEXITCODE -ne 0) { throw 'TypeScript check failed.' }
    & $workspaceNode 'node_modules\vite\bin\vite.js' build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    Write-Host 'Build ready. Run start_tris_ai.bat and open http://127.0.0.1:7860'
} finally {
    Pop-Location
    $env:PATH = $workspaceOriginalPath
}
