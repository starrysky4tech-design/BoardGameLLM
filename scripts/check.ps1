# 検証コマンド一式(lint・フォーマット確認・型検査・依存方向・テスト)。実機テストは含まない。
# 1つでも失敗したらその終了コードで止まる
# uv が PATH に無い環境でも動くよう、導入先(03の実行環境)を先頭に加える
$env:PATH = "$env:APPDATA\Python\Python314\Scripts;$env:PATH"
$env:PYTHONUTF8 = '1'
Set-Location (Split-Path $PSScriptRoot)
$steps = @(
    @('ruff', 'check', '.'),
    @('ruff', 'format', '--check', '.'),
    @('mypy'),
    @('lint-imports'),
    @('pytest')
)
foreach ($s in $steps) {
    uv run @s
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
