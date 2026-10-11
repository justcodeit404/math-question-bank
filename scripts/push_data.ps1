# Math bank hot-update. Live files already sit at /home/ubuntu/kaoyan/apps/bank-math
# (release apps/bank-math is a symlink; pack never copies this tree).
# Usage: powershell -File apps/bank-math/scripts/push_data.ps1
# Optional: -SkipGenerate -Book 1000
[CmdletBinding()]
param(
    [string]$Server = "ubuntu@122.51.26.195",
    [string]$RemoteDir = "/home/ubuntu/kaoyan/apps/bank-math",
    [string]$Book = "",
    [switch]$SkipGenerate
)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path $PSScriptRoot -Parent
$RepoRoot = Split-Path (Split-Path $Root -Parent) -Parent
$StateFile = Join-Path $PSScriptRoot "cloud_push_hash.txt"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
$Ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
$Scp = "C:\Windows\System32\OpenSSH\scp.exe"
if (-not (Test-Path -LiteralPath $Ssh)) { $Ssh = "ssh" }
if (-not (Test-Path -LiteralPath $Scp)) { $Scp = "scp" }

function Die([string]$Msg) { Write-Error $Msg; exit 1 }
function Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Invoke-WithRetry([string]$Label, [scriptblock]$Cmd) {
    for ($i = 1; $i -le 5; $i++) {
        & $Cmd
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "$Label failed (attempt $i/5), retrying..."
        Start-Sleep -Seconds 15
    }
    Die "$Label failed after 5 attempts"
}

# Book folder names are Chinese. Discover them; HTTP paths are percent-encoded so the remote command stays ASCII.
$Books = @()
Get-ChildItem -LiteralPath $Root -Directory | ForEach-Object {
    $index = Join-Path $_.FullName "math-bank\index.html"
    if (-not (Test-Path -LiteralPath $index)) { return }
    if ($Book -and $_.Name -ne $Book -and $_.Name -notlike "$Book*") { return }
    $enc = [uri]::EscapeDataString($_.Name)
    $Books += [pscustomobject]@{ Name = $_.Name; Enc = $enc; Dir = (Join-Path $_.Name "math-bank") }
}
if ($Books.Count -eq 0) { Die "no math-bank directories under $Root" }

if (-not $SkipGenerate) {
    Push-Location $Root
    try {
        & $Python scripts/generate_data_js.py --bank all
        if ($LASTEXITCODE -ne 0) { Die "generate_data_js.py failed" }
        & $Python scripts/generate_viewer.py --bank all
        if ($LASTEXITCODE -ne 0) { Die "generate_viewer.py failed" }
    } finally { Pop-Location }
}

# Live tree is already outside the release. HTTP stamp check below is the real proof.
& $Ssh -o BatchMode=yes -o ConnectTimeout=12 $Server "test -d $RemoteDir"
if ($LASTEXITCODE -ne 0) { Die "remote $RemoteDir missing" }

$old = @{}
if (Test-Path -LiteralPath $StateFile) {
    foreach ($line in (Get-Content -LiteralPath $StateFile -Encoding UTF8)) {
        if ($line -match '^\s*([^=]+)=(.+)$') { $old[$matches[1].Trim()] = $matches[2].Trim() }
    }
}
$new = @{}
$toPush = New-Object System.Collections.Generic.List[object]
$stamps = @{}
foreach ($b in $Books) {
    foreach ($name in @("data.js", "index.html")) {
        $p = Join-Path $Root (Join-Path $b.Dir $name)
        if (-not (Test-Path -LiteralPath $p)) { Die "missing $p" }
        $key = "$($b.Enc)/$name"
        $h = Sha256 $p
        $new[$key] = $h
        if ($old[$key] -ne $h) {
            $toPush.Add([pscustomobject]@{ Key = $key; Local = $p; RemoteSub = "$($b.Name)/math-bank"; Name = $name; Enc = $b.Enc })
        }
    }
    $html = Get-Content -LiteralPath (Join-Path $Root (Join-Path $b.Dir "index.html")) -Raw -Encoding UTF8
    $ver = [regex]::Match($html, 'data\.js\?v=([0-9a-f]+)').Groups[1].Value
    if (-not $ver) { Die "stamp missing in $($b.Name)" }
    $stamps[$b.Enc] = $ver
}
$stats = Join-Path $Root "stats.js"
if (Test-Path -LiteralPath $stats) {
    $h = Sha256 $stats
    $new["stats.js"] = $h
    if ($old["stats.js"] -ne $h) {
        $toPush.Add([pscustomobject]@{ Key = "stats.js"; Local = $stats; RemoteSub = ""; Name = "stats.js"; Enc = "" })
    }
}
if ($toPush.Count -eq 0) { Write-Host "no changes, nothing to push"; exit 0 }
Write-Host ("pushing {0} file(s) to {1}:{2}" -f $toPush.Count, $Server, $RemoteDir)

foreach ($g in ($toPush | Group-Object RemoteSub)) {
    $src = @($g.Group | ForEach-Object { $_.Local })
    $sub = $g.Name
    $dest = if ($sub) { "${Server}:${RemoteDir}/$sub/" } else { "${Server}:${RemoteDir}/" }
    Invoke-WithRetry "scp $sub" { & $Scp -C $src $dest }
}

$expectArg = ($stamps.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join " "
$remoteScript = 'set -e; for pair in {0}; do enc=${{pair%%=*}}; ver=${{pair#*=}}; html=$(curl -fsS "http://127.0.0.1:8000/banks/math/$enc/math-bank/index.html"); printf ''%s'' "$html" | grep -q "data.js?v=$ver" && echo "$enc stamp_ok" || {{ echo "$enc stamp_miss"; exit 1; }}; code=$(curl -sS -o /dev/null -w ''%{{http_code}}'' "http://127.0.0.1:8000/banks/math/$enc/math-bank/data.js"); echo "$enc data $code"; [ "$code" = 200 ] || exit 1; done' -f $expectArg
$remoteOut = $null
for ($i = 1; $i -le 5 -and -not $remoteOut; $i++) {
    $remoteOut = & $Ssh -o BatchMode=yes -o ConnectTimeout=15 $Server $remoteScript 2>$null
    if (-not $remoteOut) { Write-Host "verify ssh failed (attempt $i/5), retrying..."; Start-Sleep -Seconds 15 }
}
if (-not $remoteOut) { Die "verify ssh failed after 5 attempts" }
Write-Host "remote: $($remoteOut -join '; ')"
foreach ($line in $remoteOut) {
    if ($line -match "stamp_miss|data (?!200)") { Die "remote check failed: '$line'" }
}
($new.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Set-Content -LiteralPath $StateFile -Encoding UTF8
Write-Host "OK: $($toPush.Count) file(s) hot-updated (no service restart)"
