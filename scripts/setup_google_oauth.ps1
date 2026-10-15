$ErrorActionPreference = "Stop"

Write-Host "Tris AI - Google OAuth local setup" -ForegroundColor Cyan
Write-Host "Authorized redirect URI:" -ForegroundColor Yellow
Write-Host "http://127.0.0.1:8000/v1/auth/oauth/google/callback"
Write-Host ""

$clientId = (Read-Host "Google OAuth Client ID").Trim()
if ([string]::IsNullOrWhiteSpace($clientId)) {
    throw "Client ID cannot be empty."
}

$secureSecret = Read-Host "Google OAuth Client Secret (hidden)" -AsSecureString
$secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
try {
    $clientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
}
if ([string]::IsNullOrWhiteSpace($clientSecret)) {
    throw "Client Secret cannot be empty."
}

$sessionBytes = New-Object byte[] 48
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $random.GetBytes($sessionBytes)
} finally {
    $random.Dispose()
}
$sessionSecret = [Convert]::ToBase64String($sessionBytes)

[Environment]::SetEnvironmentVariable("GOOGLE_OAUTH_CLIENT_ID", $clientId, "User")
[Environment]::SetEnvironmentVariable("GOOGLE_OAUTH_CLIENT_SECRET", $clientSecret, "User")
[Environment]::SetEnvironmentVariable("TUTOR_OAUTH_SESSION_SECRET", $sessionSecret, "User")
[Environment]::SetEnvironmentVariable(
    "OAUTH_PUBLIC_BASE_URL", "http://127.0.0.1:8000", "User"
)
[Environment]::SetEnvironmentVariable(
    "WEB_PUBLIC_BASE_URL", "http://127.0.0.1:7860", "User"
)

$clientSecret = $null
$secureSecret.Dispose()
Write-Host "Google OAuth was stored in Windows user environment variables." -ForegroundColor Green
Write-Host "Restart Tris AI so the new credentials are loaded."
