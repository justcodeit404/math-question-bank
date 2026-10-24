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

# ---- static figures: images/ + answer_crops/ 也在 live 树里，改图必须跟着上云 ----
$assetDirs = @("images", "answer_crops")
$assetFiles = @()
foreach ($b in $Books) {
    $bankDir = Join-Path $Root $b.Dir
    foreach ($d in $assetDirs) {
        $dir = Join-Path $bankDir $d
        if (-not (Test-Path -LiteralPath $dir -PathType Container)) { continue }
        Get-ChildItem -LiteralPath $dir -Recurse -File | ForEach-Object {
            $rel = $_.FullName.Substring($dir.Length + 1).Replace("\", "/")
            $assetFiles += [pscustomobject]@{
                Book  = $b.Name
                Enc   = $b.Enc
                Dir   = $d
                Rel   = $rel
                Key   = "$($b.Enc)/$d/$rel"
                Local = $_.FullName
                Hash  = (Sha256 $_.FullName)
            }
        }
    }
}

# 首次接入：用云端现有文件哈希回填基线，避免把 1GB 题图全量重传。
# 所有书目合并成一次 SSH，减少建连（云端对短时间多次 SSH 建连有限流）。
if (@($assetFiles | Where-Object { -not $old.ContainsKey($_.Key) }).Count -gt 0) {
    $seedParts = foreach ($b in $Books) {
        $dir = "`$D/$($b.Name)/math-bank"
        "if [ -d `"$dir`" ]; then echo `"##$($b.Enc)`"; (cd `"$dir`" && find images answer_crops -type f -exec sha256sum {} + 2>/dev/null); fi"
    }
    $remoteSeed = "D='$RemoteDir'; " + ($seedParts -join '; ')
    $currentEnc = $null
    foreach ($line in @(& $Ssh -o BatchMode=yes -o ConnectTimeout=15 $Server $remoteSeed 2>$null)) {
        if ($line -match '^##(.+)$') { $currentEnc = $matches[1]; continue }
        if ($currentEnc -and $line -match '^([0-9a-f]{64})\s+(.+)$') {
            $old["$currentEnc/$($matches[2])"] = $matches[1]
        }
    }
    Start-Sleep -Seconds 3
}

$assetDrift = @{}
foreach ($a in $assetFiles) {
    $new[$a.Key] = $a.Hash
    if ($old[$a.Key] -ne $a.Hash) { $assetDrift["$($a.Book)|$($a.Dir)"] = $true }
}

# ---- 本地删除/改名的文件云端也要删 ----
# 只按哈希增量推的话，重命名过的裁图、删掉的题库文件会永远留在云上（同名 URL 还能命中旧图）。
# 范围限定在本次运行涉及的书目（-Book 时不能误删其它书），stats.js 单独算。
$scopePrefixes = @($Books | ForEach-Object { "$($_.Enc)/" }) + @("stats.js")
$removed = New-Object System.Collections.Generic.List[string]
foreach ($k in @($old.Keys)) {
    if ($new.ContainsKey($k)) { continue }
    if (-not ($scopePrefixes | Where-Object { $k -eq "stats.js" -or $k.StartsWith($_) })) { continue }
    $removed.Add($k)
}
# 本次没涉及的书目（-Book 过滤）保持原样写回状态文件，否则下次要重新 SSH 回填基线
foreach ($k in @($old.Keys)) {
    if (-not $new.ContainsKey($k) -and -not $removed.Contains($k)) { $new[$k] = $old[$k] }
}
# key 里的书目段是 percent-encoded（只作标识），真实路径要用目录名
function RemoteRelPath([string]$Key) {
    if ($Key -eq "stats.js") { return $Key }
    foreach ($b in $Books) {
        if ($Key.StartsWith("$($b.Enc)/")) { return "$($b.Name)/math-bank/" + $Key.Substring($b.Enc.Length + 1) }
    }
    return $null
}

if ($toPush.Count -eq 0 -and $assetDrift.Count -eq 0 -and $removed.Count -eq 0) {
    Write-Host "no changes, nothing to push"
    exit 0
}
Write-Host ("pushing {0} file(s) to {1}:{2}" -f $toPush.Count, $Server, $RemoteDir)

foreach ($g in ($toPush | Group-Object RemoteSub)) {
    $src = @($g.Group | ForEach-Object { $_.Local })
    $sub = $g.Name
    $dest = if ($sub) { "${Server}:${RemoteDir}/$sub/" } else { "${Server}:${RemoteDir}/" }
    Invoke-WithRetry "scp $sub" { & $Scp -C $src $dest }
    Start-Sleep -Seconds 2
}

# 漂移的题图目录：整目录 tar → scp → 远端解包（PNG 已压缩，不再 -C）
# 解包和文件数校验放在同一次 SSH 里，减少建连次数。
if ($assetDrift.Count -gt 0) {
    $Tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (-not (Test-Path -LiteralPath $Tar)) { Die "tar.exe not found for asset push" }
    foreach ($item in @($assetDrift.Keys)) {
        $bookName, $dirName = $item -split '\|', 2
        $bankDir = Join-Path $Root (Join-Path $bookName "math-bank")
        $remoteBank = "$RemoteDir/$bookName/math-bank"
        $tarName = ".bankmath-$([guid]::NewGuid().ToString('N')).tar"
        $tmpTar = Join-Path $env:TEMP $tarName
        $localCount = @($assetFiles | Where-Object { $_.Book -eq $bookName -and $_.Dir -eq $dirName }).Count
        try {
            & $Tar -C $bankDir -cf $tmpTar $dirName
            if ($LASTEXITCODE -ne 0) { Die "tar pack failed: $item" }
            Invoke-WithRetry "scp $item" { & $Scp $tmpTar "${Server}:/tmp/$tarName" }
            $remoteCount = $null
            for ($i = 1; $i -le 5 -and $null -eq $remoteCount; $i++) {
                $out = & $Ssh -o BatchMode=yes -o ConnectTimeout=15 $Server "tar -C '$remoteBank' -xf '/tmp/$tarName' && rm -f '/tmp/$tarName' && find '$remoteBank/$dirName' -type f | wc -l" 2>&1
                if ($LASTEXITCODE -eq 0 -and "$out".Trim() -match '^\d+$') {
                    $remoteCount = [int]("$out".Trim())
                } else {
                    Write-Host "ssh extract $item failed (attempt $i/5): $($out -join ' ')"
                    Start-Sleep -Seconds 15
                }
            }
            if ($null -eq $remoteCount) { Die "ssh extract failed: $item" }
            if ($remoteCount -ne $localCount) {
                Die "asset count mismatch at $item (local=$localCount remote=$remoteCount)"
            }
            Write-Host "assets ok: $item ($localCount)"
        } finally {
            if (Test-Path -LiteralPath $tmpTar) { Remove-Item -LiteralPath $tmpTar -Force }
        }
        Start-Sleep -Seconds 2
    }
}

# 删除放在推送之后：先让新文件落地，再清旧路径，中间不会出现「文件先没了」的窗口
if ($removed.Count -gt 0) {
    $rmPaths = @($removed | ForEach-Object { $rel = RemoteRelPath $_; if ($rel) { "'" + $rel + "'" } })
    if ($rmPaths.Count -gt 0) {
        Write-Host ("removing {0} deleted file(s) from remote" -f $rmPaths.Count)
        $rmScript = "cd '$RemoteDir' && rm -f -- " + ($rmPaths -join ' ')
        Invoke-WithRetry "remote rm" { & $Ssh -o BatchMode=yes -o ConnectTimeout=15 $Server $rmScript }
    }
}

$expectArg = ($stamps.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join " "

# 发布校验直接看公网 HTTP，不再额外建 SSH 连接（云端对短时间多次 SSH 建连有限流）。
$httpBase = "http://122.51.26.195"
function Get-Http([string]$Url) {
    for ($i = 1; $i -le 5; $i++) {
        try {
            return Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20
        } catch {
            if ($i -eq 5) { Die "HTTP failed: $Url ($($_.Exception.Message))" }
            Start-Sleep -Seconds 5
        }
    }
}
foreach ($pair in $stamps.GetEnumerator()) {
    $enc = $pair.Key
    $ver = $pair.Value
    $html = (Get-Http "$httpBase/banks/math/$enc/math-bank/index.html").Content
    if ($html -notmatch [regex]::Escape("data.js?v=$ver")) { Die "$enc stamp_miss (expect $ver)" }
    $code = (Get-Http "$httpBase/banks/math/$enc/math-bank/data.js").StatusCode
    if ($code -ne 200) { Die "$enc data $code" }
    Write-Host "remote: $enc stamp_ok data 200"
}

($new.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Set-Content -LiteralPath $StateFile -Encoding UTF8
Write-Host "OK: $($toPush.Count) file(s) + $($assetDrift.Count) asset dir(s) hot-updated (no service restart)"
