$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$postgresBin = Join-Path $projectRoot "runtime\postgresql-17.11\pgsql\bin"
$clusterPath = Join-Path $projectRoot "data\postgres-account-db"
$logPath = Join-Path $projectRoot "data\postgres-account-db.log"

if (-not (Test-Path (Join-Path $postgresBin "postgres.exe"))) {
    throw "PostgreSQL portable runtime is missing."
}

function New-RandomHexSecret {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToHexString($bytes).ToLower()
}

$superSecret = [Environment]::GetEnvironmentVariable(
    "TUTOR_PG_SUPER_SECRET", "User"
)
if (-not $superSecret) {
    $superSecret = New-RandomHexSecret
}
[Environment]::SetEnvironmentVariable(
    "TUTOR_PG_SUPER_SECRET", $superSecret, "User"
)

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
            --pwfile=$($secretFile.FullName)
        if ($LASTEXITCODE -ne 0) {
            throw "initdb failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        if (Test-Path -LiteralPath $secretFile.FullName) {
            Remove-Item -LiteralPath $secretFile.FullName -Force
        }
    }
}

& (Join-Path $postgresBin "pg_ctl.exe") -D $clusterPath status 2>$null
if ($LASTEXITCODE -ne 0) {
    & (Join-Path $postgresBin "pg_ctl.exe") `
        -D $clusterPath `
        -l $logPath `
        -o '"-p 5432"' `
        start
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL failed to start."
    }
}

$env:PGPASSWORD = $superSecret
$appSecret = New-RandomHexSecret
$psql = Join-Path $postgresBin "psql.exe"
& $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 `
    -c "ALTER ROLE postgres PASSWORD '$superSecret'" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not secure the PostgreSQL administrator role."
}
$roleExists = [string](& $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -tAc `
    "SELECT 1 FROM pg_roles WHERE rolname='english_tutor'")
$roleExists = if ($null -eq $roleExists) { "" } else { $roleExists.Trim() }
if ($roleExists -eq "1") {
    & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 `
        -c "ALTER ROLE english_tutor PASSWORD '$appSecret'" | Out-Null
}
else {
    & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 `
        -c "CREATE ROLE english_tutor LOGIN PASSWORD '$appSecret'"
}
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the English Tutor PostgreSQL role."
}

$databaseExists = [string](& $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -tAc `
    "SELECT 1 FROM pg_database WHERE datname='english_tutor_accounts'")
$databaseExists = if ($null -eq $databaseExists) { "" } else { $databaseExists.Trim() }
if ($databaseExists -ne "1") {
    & (Join-Path $postgresBin "createdb.exe") `
        -h 127.0.0.1 `
        -p 5432 `
        -U postgres `
        -O english_tutor `
        english_tutor_accounts
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the English Tutor PostgreSQL database."
    }
}

$dsn = "postgresql://english_tutor:$appSecret@127.0.0.1:5432/english_tutor_accounts"
[Environment]::SetEnvironmentVariable("TUTOR_POSTGRES_DSN", $dsn, "User")
[Environment]::SetEnvironmentVariable(
    "TUTOR_PG_SUPER_SECRET", $superSecret, "User"
)

Write-Output "PostgreSQL account database is ready on 127.0.0.1:5432."
& (Join-Path $postgresBin "pg_isready.exe") -h 127.0.0.1 -p 5432
