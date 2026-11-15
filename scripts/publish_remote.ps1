# BoardGameLLM の作業ツリーを、公開用のリモート(GitHub)へ送る。
#
# 方式: リモートを一時フォルダへ clone し、Git 管理対象(追跡中 + 除外されていないもの)のファイルを
# 上書きコピーしてコミットし、push する。リモートの履歴は書き換えない(fast-forward のみ)。
# 元のリポジトリ全体の履歴を切り出して送る方式は、リモートの履歴と食い違うので使わない。
#
# 使い方:
#   .\scripts\publish_remote.ps1 -Message "feat(hive): ..."          # コミットして push
#   .\scripts\publish_remote.ps1 -Message "..." -DryRun              # 変更を確かめるだけ(push しない)
#   .\scripts\publish_remote.ps1 -Message "..." -SkipCheck           # 検証(check.ps1)を省く

param(
    [Parameter(Mandatory = $true)][string]$Message,
    [string]$Remote = "https://github.com/starrysky4tech-design/BoardGameLLM.git",
    [string]$Branch = "main",
    [string[]]$Exclude = @(),  # 送らないファイル(BoardGameLLM からの相対パス。例: .claude/settings.json)
    [switch]$DryRun,
    [switch]$SkipCheck
)

$ErrorActionPreference = "Stop"
# git の出力(UTF-8)を、日本語のファイル名のまま読めるようにする(既定の cp932 だと化ける)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$project = Split-Path $PSScriptRoot -Parent            # BoardGameLLM のルート
# BoardGameLLM 直下には、リモートを clone した別の .git があることがある。そのため、
# 親のリポジトリ(LLMProject の上の作業リポジトリ)を基準にして、対象のファイルを決める
$repo = (git -C (Split-Path $project -Parent) rev-parse --show-toplevel).Trim()
$prefix = [System.IO.Path]::GetRelativePath([System.IO.Path]::GetFullPath($repo), [System.IO.Path]::GetFullPath($project)) -replace '\\', '/'

if (-not $SkipCheck) {
    Write-Host "検証: check.ps1 を実行する"
    & (Join-Path $project "scripts\check.ps1")
    if ($LASTEXITCODE -ne 0) { throw "検証に失敗したので、送らない" }
}

# 送るファイル: 追跡中のもの + 除外設定に掛からない未追跡のもの(.gitignore の対象は含めない)
$files = git -c core.quotepath=off -C $repo ls-files --cached --others --exclude-standard -- $prefix |
    ForEach-Object { $_.Substring($prefix.Length + 1) } |
    Where-Object { $Exclude -notcontains $_ }

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("publish-bgl-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
git clone -q --branch $Branch $Remote $work
if ($LASTEXITCODE -ne 0) { throw "clone に失敗した: $Remote" }

# リモートにあって、いまの作業ツリーには無いファイルは削除する
Get-ChildItem -Path $work -Recurse -File | Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' } | ForEach-Object {
    $rel = $_.FullName.Substring($work.Length + 1) -replace '\\', '/'
    # 除外したファイルは、リモートの内容をそのまま残す
    if (($files -notcontains $rel) -and ($Exclude -notcontains $rel)) { Remove-Item $_.FullName -Force }
}

foreach ($rel in $files) {
    $src = Join-Path $project ($rel -replace '/', '\')
    if (-not (Test-Path $src)) { continue }  # 削除済みの追跡ファイル
    $dst = Join-Path $work ($rel -replace '/', '\')
    New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
    Copy-Item -Force $src $dst
}

git -C $work add -A
$changed = git -C $work status --porcelain
if (-not $changed) {
    Write-Host "リモートと同じ内容。送るものは無い"
    Remove-Item -Recurse -Force $work
    exit 0
}
Write-Host "送る変更:"
git -C $work status --short

if ($DryRun) {
    Write-Host "DryRun: push しない。一時フォルダ: $work"
    exit 0
}

git -C $work commit -q -m $Message
git -C $work push -q origin $Branch
if ($LASTEXITCODE -ne 0) { throw "push に失敗した(一時フォルダ: $work)" }
Write-Host "push 完了: $Remote ($Branch)"
Remove-Item -Recurse -Force $work
