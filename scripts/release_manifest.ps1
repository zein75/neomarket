param(
    [string]$OutputPath = "release-manifest.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$contractFiles = Get-ChildItem "docs/NEOMARKET_PRODUCTION_SPEC_V2_2026-10-14/contracts" -Filter "*.yaml" -File | Sort-Object FullName
$contractHashes = @{}
foreach ($file in $contractFiles) {
    $relative = $file.FullName.Substring($repoRoot.Length + 1).Replace("\", "/")
    $contractHashes[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
}

$migrationHashes = @{}
$migrationHeads = @{}
foreach ($service in @("b2b", "b2c", "admin")) {
    $path = Join-Path $repoRoot "services/$service/migrations/versions"
    $files = @(Get-ChildItem $path -Filter "*.py" -File | Sort-Object Name)
    $revisions = @{}
    $parents = @{}
    $migrationHashes[$service] = @(
        $files | ForEach-Object {
            $content = Get-Content -Raw -LiteralPath $_.FullName
            $revision = [regex]::Match($content, '(?m)^revision\s*=\s*["'']([^"'']+)["'']').Groups[1].Value
            $parent = [regex]::Match($content, '(?m)^down_revision\s*=\s*["'']([^"'']+)["'']').Groups[1].Value
            if ($revision) { $revisions[$revision] = $true }
            if ($parent) { $parents[$parent] = $true }
            [ordered]@{
                file = $_.Name
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            }
        }
    )
    $migrationHeads[$service] = @($revisions.Keys | Where-Object { -not $parents.ContainsKey($_) } | Sort-Object)
}

$gitSha = (git rev-parse HEAD).Trim()
$manifest = [ordered]@{
    git_sha = $gitSha
    image_digests = [ordered]@{
        b2b = if ($env:B2B_IMAGE_DIGEST) { $env:B2B_IMAGE_DIGEST } else { $null }
        b2c = if ($env:B2C_IMAGE_DIGEST) { $env:B2C_IMAGE_DIGEST } else { $null }
        admin = if ($env:ADMIN_IMAGE_DIGEST) { $env:ADMIN_IMAGE_DIGEST } else { $null }
    }
    contract_sha256 = $contractHashes
    migration_heads = $migrationHeads
    migrations = $migrationHashes
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
}

$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 -LiteralPath $OutputPath
Write-Output "Release manifest written to $OutputPath"
