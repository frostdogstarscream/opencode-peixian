[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('enable','disable','status','start','stop','restart','recreate','verify','export')]
    [string]$Action,
    [ValidateSet('all','client-a','client-b')]
    [string]$Client = 'all'
)
$ErrorActionPreference = 'Stop'
$deployRoot = $PSScriptRoot
$marker = Join-Path $deployRoot '.runtime/deepseek.enabled'
$projectName = 'peixian-opencode'
$baseArgs = @('compose','-p',$projectName,'-f',(Join-Path $deployRoot 'compose.yaml'))
$profileArgs = $baseArgs + @('-f',(Join-Path $deployRoot 'compose.deepseek.yaml'))
function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker failed (exit $LASTEXITCODE). Existing data volumes were preserved." }
}
if ($Action -in @('start','restart','recreate') -and -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    throw 'DeepSeek profile is disabled. Run deepseek.ps1 -Action enable before starting or rebuilding it.'
}
if ((& docker info --format '{{.OSType}}' 2>$null) -ne 'linux' -or $LASTEXITCODE -ne 0) {
    throw 'Docker Linux engine must be running.'
}
if ($Action -eq 'export') { throw 'The DeepSeek test profile is active. The existing dist package is the accepted no-model baseline. Disable the profile before exporting the baseline; this script does not export API credentials.' }
if ($Action -eq 'enable' -or $Action -eq 'start' -or $Action -eq 'recreate') {
    foreach ($name in @('client-a','client-b')) {
        foreach ($suffix in @('password','deepseek-key')) {
            $secretPath = Join-Path $deployRoot ".secrets/$name.$suffix"
            if (-not (Test-Path -LiteralPath $secretPath -PathType Leaf)) { throw "Missing private credential file: $name.$suffix" }
            $value = [IO.File]::ReadAllText($secretPath).TrimEnd([char[]]@([char]13,[char]10))
            if ($value.Length -lt 16 -or $value.IndexOfAny([char[]]@([char]13,[char]10,[char]0)) -ge 0) { throw "Invalid private credential file: $name.$suffix" }
        }
    }
    Invoke-Docker ($profileArgs + @('config','--quiet'))
}
$targets = @()
if ($Client -ne 'all') { $targets = @($Client) }
switch ($Action) {
    'enable' {
        New-Item -ItemType Directory -Path (Split-Path $marker) -Force | Out-Null
        [IO.File]::WriteAllText($marker, 'deepseek-flash', (New-Object Text.UTF8Encoding($false)))
        # Record desired profile before startup so subsequent management retries use it.
        Invoke-Docker ($profileArgs + @('up','-d','--no-build','--pull','never','--wait','--wait-timeout','180'))
    }
    'disable' {
        Invoke-Docker ($baseArgs + @('up','-d','--no-build','--pull','never','--force-recreate','--wait','--wait-timeout','180','client-a','client-b','client-a-entry','client-b-entry'))
        Invoke-Docker ($profileArgs + @('stop','--timeout','20','client-a-deepseek','client-b-deepseek'))
        if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker }
        Write-Host 'No-model baseline restored; all persistent volumes and credential files retained.'
    }
    'status' { Invoke-Docker ($profileArgs + @('ps','--all')) }
    'start' { Invoke-Docker ($profileArgs + @('up','-d','--no-build','--pull','never','--wait','--wait-timeout','180') + $targets) }
    'stop' { Invoke-Docker ($profileArgs + @('stop','--timeout','20') + $targets) }
    'restart' { Invoke-Docker ($profileArgs + @('restart','--timeout','20') + $targets) }
    'recreate' { Invoke-Docker ($profileArgs + @('up','-d','--no-build','--pull','never','--force-recreate','--wait','--wait-timeout','180') + $targets) }
    'verify' {
        & (Join-Path $deployRoot '.venv/Scripts/python.exe') (Join-Path $deployRoot 'deepseek_verify.py')
        if ($LASTEXITCODE -ne 0) { throw 'DeepSeek live verification failed; inspect the redacted report.' }
    }
}
