$ErrorActionPreference = 'Stop'
$errors = $null
$tokens = $null
$source = Join-Path $PSScriptRoot '../platform.ps1'
$tree = [System.Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors) { throw 'Platform wrapper does not parse.' }
$functions = @('Test-PlatformWorkerCommand', 'Test-PlatformCreationTime')
foreach ($name in $functions) {
    $definition = $tree.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) | Where-Object Name -eq $name
    if (@($definition).Count -ne 1) { throw 'Expected one platform process validation function.' }
    Invoke-Expression $definition.Extent.Text
}
$platformWorker = 'D:\synthetic\console-worker.py'
$platformConfig = 'D:\synthetic\platform.json'
$created = [datetime]::Parse('2026-09-15T12:00:00.1234567Z', [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
$process = [pscustomobject]@{Name='python.exe'; CreationDate=$created; CommandLine=('python -u "' + $platformWorker + '" --config "' + $platformConfig + '"')}
$roundtrip = $created.ToString('o')
$fromJson = ('{"created":"' + $roundtrip + '"}') | ConvertFrom-Json
$checks = @(
    (Test-PlatformCreationTime $process $roundtrip),
    (Test-PlatformCreationTime $process $created),
    (Test-PlatformCreationTime $process $fromJson.created),
    (-not (Test-PlatformCreationTime $process $created.AddSeconds(1))),
    (-not (Test-PlatformCreationTime $process 'invalid-time')),
    (Test-PlatformWorkerCommand $process)
)
$process.Name = 'conhost.exe'
$checks += -not (Test-PlatformWorkerCommand $process)
$process.Name = 'python.exe'
$process.CommandLine = 'python D:\other\console-worker.py --config D:\other\platform.json'
$checks += -not (Test-PlatformWorkerCommand $process)
if ($checks -contains $false) { throw 'A platform worker identity assertion failed.' }
Write-Output ('Platform worker identity checks passed: ' + $checks.Count)
