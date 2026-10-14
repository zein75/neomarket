param(
    [string]$ManifestPath = "verification-manifest.json"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:UV_CACHE_DIR = Join-Path $repoRoot ".uv-cache"

function Invoke-NativeGate([string]$Name, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Gate failed ($LASTEXITCODE): $Name" }
}

Invoke-NativeGate "uv lock --check" { uv lock --check }
Invoke-NativeGate "ruff production source" { uv run ruff check shared/shared services/b2b/src services/b2c/src services/admin/src }
Invoke-NativeGate "production specification validator" { uv run python docs/NEOMARKET_PRODUCTION_SPEC_V2_2026-10-14/qa/validate_spec.py }
Invoke-NativeGate "live OpenAPI route check" { uv run python scripts/check_openapi_routes.py }

function Invoke-ServiceTests([string]$pythonPath, [string]$testPath) {
    $previous = $env:PYTHONPATH
    $env:PYTHONPATH = $pythonPath
    try {
        Invoke-NativeGate "tests: $testPath" { uv run pytest -q $testPath }
    }
    finally {
        $env:PYTHONPATH = $previous
    }
}

Invoke-ServiceTests "services/b2c;shared" "services/b2c/tests"
Invoke-ServiceTests "services/b2b;shared" "services/b2b/tests"
Invoke-ServiceTests "services/admin;shared" "services/admin/tests"
Invoke-ServiceTests "shared" "shared/tests"
Invoke-ServiceTests "shared" "tests"

$manifest = [ordered]@{
    git_sha = (git rev-parse HEAD).Trim()
    status = "passed"
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    gates = @(
        "uv lock --check",
        "ruff production source",
        "production specification validator",
        "B2C tests",
        "B2B tests",
        "Admin tests",
        "shared tests",
        "repository tests"
    )
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 -LiteralPath $ManifestPath
Write-Output "Verification gates passed."
Write-Output "Verification manifest written to $ManifestPath"
