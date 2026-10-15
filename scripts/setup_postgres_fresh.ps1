# Fresh account cluster for a copied project whose original cluster cannot be
# administered on this machine (the superuser secret never travelled with it).
# Creates data\postgres-account-db-fresh and the standard roles/database, then
# saves TUTOR_POSTGRES_DSN exactly like scripts\setup_postgres.ps1 does.
# Only NEW files under the -fresh folder are touched.
$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent $PSScriptRoot
$postgresBin = Join-Path $projectRoot "runtime\postgresql-17.11\pgsql\bin"
$clusterPath = Join-Path $projectRoot "data\postgres-account-db-fresh"
$logPath = Join-Path $projectRoot "data\postgres-account-db-fresh.log"
$resultLog = Join-Path $projectRoot "data\fix_postgres_result.txt"
"fresh setup started $(Get-Date -Format s)" | Out-File -FilePath $resultLog -Encoding utf8

function Log($message) {
    $message | Out-File -FilePath $resultLog -Append -Encoding utf8
}

function New-RandomHexSecret {
    # Compatible with Windows PowerShell 5.1 (.NET Framework has no static
    # Fill and no Convert.ToHexString).
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [BitConverter]::ToString($bytes).Replace('-', '').ToLower()
}

if (-not (Test-Path (Join-Path $postgresBin "postgres.exe"))) {
    Log "FAILED: PostgreSQL portable runtime is missing."
    exit 1
}

$superSecret = [Environment]::GetEnvironmentVariable("TUTOR_PG_SUPER_SECRET", "User")
if (-not $superSecret) { $superSecret = New-RandomHexSecret }
$appSecret = New-RandomHexSecret
# Save both secrets before anything risky so a partial run still leaves a
# usable DSN behind.
[Environment]::SetEnvironmentVariable("TUTOR_PG_SUPER_SECRET", $superSecret, "User")

if (-not (Test-Path (Join-Path $clusterPath "PG_VERSION"))) {
    New-Item -ItemType Directory -Force -Path $clusterPath | Out-Null
    $secretFile = New-TemporaryFile
    try {
        [IO.File]::WriteAllText($secretFile.FullName, $superSecret)
        & (Join-Path $postgresBin "initdb.exe") `
            -D $clusterPath `
            -U postgres `
            --encoding=UTF8 `
            --locale=C `
            --auth-host=scram-sha-256 `
            --auth-local=scram-sha-256 `
            --pwfile=$($secretFile.FullName) 2>&1 | ForEach-Object { Log "initdb: $_" }
        if ($LASTEXITCODE -ne 0) {
            Log "FAILED: initdb exited with code $LASTEXITCODE."
            exit 1
        }
    }
    finally {
        if (Test-Path -LiteralPath $secretFile.FullName) {
            Remove-Item -LiteralPath $secretFile.FullName -Force
        }
    }
    Log "Fresh cluster initialized."
} else {
    Log "Fresh cluster already exists; reusing it."
}

# Launch pg_ctl with NO captured pipes and NO -Wait: the started server
# inherits every handle pg_ctl owns, so waiting on pg_ctl or its redirected
# streams blocks until the server itself exits. Poll readiness instead.
Start-Process -FilePath (Join-Path $postgresBin "pg_ctl.exe") `
    -ArgumentList @('-D', ('"{0}"' -f $clusterPath), '-l', ('"{0}"' -f $logPath), '-w', '-t', '60', 'start') `
    -WindowStyle Hidden | Out-Null
$ready = $null
foreach ($attempt in 1..30) {
    Start-Sleep -Seconds 2
    $ready = & (Join-Path $postgresBin "pg_isready.exe") -h 127.0.0.1 -p 5432 2>&1
    if ("$ready" -match "accepting connections") { break }
}
Log "pg_isready: $ready"
$ready = & (Join-Path $postgresBin "pg_isready.exe") -h 127.0.0.1 -p 5432 2>&1
Log "pg_isready: $ready"
if ($ready -notmatch "accepting connections") {
    Get-Content $logPath -Tail 10 -ErrorAction SilentlyContinue | ForEach-Object { Log "  log: $_" }
    Log "FAILED: server did not become ready."
    exit 1
}

$env:PGPASSWORD = $superSecret
$psql = Join-Path $postgresBin "psql.exe"

& $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 `
    -c "ALTER ROLE postgres PASSWORD '$superSecret'" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Log "FAILED: could not secure the postgres role."; exit 1 }

$roleExists = [string](& $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -tAc `
    "SELECT 1 FROM pg_roles WHERE rolname='english_tutor'")
if ("$roleExists".Trim() -eq "1") {
    & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 `
        -c "ALTER ROLE english_tutor PASSWORD '$appSecret'" 2>&1 | Out-Null
} else {
    & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 `
        -c "CREATE ROLE english_tutor LOGIN PASSWORD '$appSecret'" 2>&1 | Out-Null
}
if ($LASTEXITCODE -ne 0) { Log "FAILED: could not create the english_tutor role."; exit 1 }

& (Join-Path $postgresBin "createdb.exe") `
    -h 127.0.0.1 -p 5432 -U postgres -O english_tutor english_tutor_accounts 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Log "FAILED: could not create english_tutor_accounts."; exit 1 }
Log "Role and database ready."

$dsn = "postgresql://english_tutor:$appSecret@127.0.0.1:5432/english_tutor_accounts"
[Environment]::SetEnvironmentVariable("TUTOR_POSTGRES_DSN", $dsn, "User")
[Environment]::SetEnvironmentVariable("TUTOR_PG_SUPER_SECRET", $superSecret, "User")
Log "TUTOR_POSTGRES_DSN saved to user environment."

$env:PGPASSWORD = $appSecret
$probe = & $psql -h 127.0.0.1 -p 5432 -U english_tutor -d english_tutor_accounts -tAc "SELECT 1" 2>&1
if ("$probe".Trim() -eq "1") { Log "SCRAM login with the new DSN works." } else { Log "WARNING: DSN login probe failed: $probe" }
Log "fresh setup finished $(Get-Date -Format s)"
