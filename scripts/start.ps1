param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $AstralArguments = @("ui")
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location -LiteralPath $ProjectRoot

& conda run --no-capture-output -n pytorch_env `
    python -m astral_agents.cli @AstralArguments
exit $LASTEXITCODE
