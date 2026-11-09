param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = "1.13.5"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $projectRoot ".tools\terraform\$Version"
$null = New-Item -ItemType Directory -Path $destination -Force
$archiveName = "terraform_${Version}_windows_amd64.zip"
$archive = Join-Path $destination $archiveName
$checksum = Join-Path $destination "SHA256SUMS"
$base = "https://releases.hashicorp.com/terraform/$Version"
Invoke-WebRequest -UseBasicParsing -Uri "$base/$archiveName" -OutFile $archive
Invoke-WebRequest -UseBasicParsing -Uri "$base/terraform_${Version}_SHA256SUMS" -OutFile $checksum
$expectedLine = Get-Content -LiteralPath $checksum | Where-Object { $_.Trim().EndsWith($archiveName) }
if (-not $expectedLine) { throw "No matching checksum for $archiveName" }
$expected = ($expectedLine.Trim() -split '\s+')[0]
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actual -ine $expected) { throw "Terraform download checksum mismatch; archive was not executed." }
Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
& (Join-Path $destination "terraform.exe") version
