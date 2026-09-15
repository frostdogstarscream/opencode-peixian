[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('init','render','check','up','stop','status','worker','worker-start','worker-stop','backup','verify-backup','restore','upgrade-backup')]
    [string]$Action,
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$Python,
    [string]$Archive,
    [string]$Destination
)
$ErrorActionPreference = 'Stop'
$platformConfig = (Resolve-Path -LiteralPath $Config).Path
$platformRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
if (-not $Python) {
    $platformCandidate = Join-Path $platformRepo 'services/peixian-control/.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $platformCandidate) { $Python = $platformCandidate }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
$platformPython = (Get-Command $Python -ErrorAction Stop).Source
$platformManager = Join-Path $PSScriptRoot 'platform-manage.py'
$platformWorker = Join-Path $PSScriptRoot 'console-worker.py'
$platformPathsCode = @'
import importlib.util,json,pathlib,sys
spec=importlib.util.spec_from_file_location('platform_config',pathlib.Path(sys.argv[1])/'platform-config.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
cfg=module.load_config(sys.argv[2])
print(json.dumps({'root':str(cfg.worker_root),'control_url':cfg.control_url,'key':str(cfg.secrets/'console-worker.key')}))
'@
$platformPathsOutput = & $platformPython -c $platformPathsCode $PSScriptRoot $platformConfig
if ($LASTEXITCODE -ne 0) { throw 'Platform configuration is invalid; no service was changed.' }
$platformPaths = $platformPathsOutput | ConvertFrom-Json
$platformRecord = Join-Path $platformPaths.root 'windows-worker.process.json'

function Invoke-PlatformManager([string]$Command) {
    $platformArguments = @($platformManager, $Command, '--config', $platformConfig)
    if ($Archive) { $platformArguments += @('--archive', $Archive) }
    if ($Destination) { $platformArguments += @('--destination', $Destination) }
    & $platformPython @platformArguments
    if ($LASTEXITCODE -ne 0) { throw 'Platform operation failed; existing data was preserved.' }
}

function Test-PlatformWorkerCommand($Process) {
    return ($Process -and $Process.CreationDate -and $Process.CommandLine -and
        $Process.Name -match '^python(?:w|[0-9.]*)?\.exe$' -and
        $Process.CommandLine.Contains($platformWorker) -and $Process.CommandLine.Contains($platformConfig))
}

function Test-PlatformCreationTime($Process, $Saved) {
    try {
        $savedTime = if ($Saved -is [datetime]) { $Saved } else {
            [datetime]::Parse([string]$Saved, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
        }
        return ($Process.CreationDate.ToUniversalTime().Ticks -eq $savedTime.ToUniversalTime().Ticks)
    } catch { return $false }
}

function Find-PlatformWorkerChildren($Seed, [int]$Depth) {
    $children = @(Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $Seed.ProcessId) -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        if ((Test-PlatformWorkerCommand $child) -and $child.CreationDate -ge $Seed.CreationDate) {
            [pscustomobject]@{ process=$child; depth=$Depth }
            Find-PlatformWorkerChildren $child ($Depth + 1)
        }
    }
}

function Get-PlatformWorker {
    if (-not (Test-Path -LiteralPath $platformRecord)) { return }
    $record = Get-Content -LiteralPath $platformRecord -Raw | ConvertFrom-Json
    if ($record.script -ne $platformWorker -or $record.config -ne $platformConfig) { throw 'Worker record belongs to another configuration.' }
    $saved = if ($record.processes) { @($record.processes) } else { @(@{pid=$record.pid;created=$record.created;depth=0}) }
    $found = @{}
    foreach ($entry in $saved) {
        $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$entry.pid) -ErrorAction SilentlyContinue
        if (-not (Test-PlatformWorkerCommand $process)) { continue }
        if (-not (Test-PlatformCreationTime $process $entry.created)) { continue }
        $found[[string]$process.ProcessId] = [pscustomobject]@{process=$process;depth=[int]$entry.depth}
        foreach ($child in @(Find-PlatformWorkerChildren $process ([int]$entry.depth + 1))) {
            $found[[string]$child.process.ProcessId] = $child
        }
    }
    return @($found.Values)
}

function Start-PlatformWorker {
    if (Get-PlatformWorker) { Write-Host 'This platform worker is already running.'; return }
    if (-not (Test-Path -LiteralPath $platformPaths.root -PathType Container)) { throw 'Initialize this platform before starting its worker.' }
    $arguments = @('-u', ('"' + $platformWorker + '"'), '--config', ('"' + $platformConfig + '"'))
    $process = Start-Process -FilePath $platformPython -ArgumentList $arguments -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $platformPaths.root 'windows-worker.stdout.log') -RedirectStandardError (Join-Path $platformPaths.root 'windows-worker.stderr.log') -PassThru
    Start-Sleep -Seconds 2
    if ($process.HasExited) { throw 'The worker did not start. Inspect this deployment worker log.' }
    $identity = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $process.Id)
    $identities = @([pscustomobject]@{process=$identity;depth=0}) + @(Find-PlatformWorkerChildren $identity 1)
    $saved = @($identities | ForEach-Object { @{pid=$_.process.ProcessId;created=$_.process.CreationDate.ToUniversalTime().ToString('o');depth=$_.depth} })
    $actual = $identities | Sort-Object depth -Descending | Select-Object -First 1
    @{ version=2; script=$platformWorker; config=$platformConfig; processes=$saved } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $platformRecord -Encoding utf8
    Write-Host ('This platform worker started; runtime process ' + $actual.process.ProcessId)
}

function Stop-PlatformWorker {
    $processes = @(Get-PlatformWorker)
    if (-not $processes) { Write-Host 'This platform has no tracked worker to stop.'; return }
    $check = @'
import json,pathlib,sys,urllib.request
try:
    key=pathlib.Path(sys.argv[2]).read_text().strip()
    request=urllib.request.Request(sys.argv[1]+'/internal/worker/busy',headers={'X-Worker-Key':key})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    busy=json.load(opener.open(request,timeout=5)).get('busy',True)
except Exception:
    busy=True
sys.exit(2 if busy else 0)
'@
    & $platformPython -c $check $platformPaths.control_url $platformPaths.key
    if ($LASTEXITCODE -ne 0) { throw 'Worker may be applying a configuration. Wait until it is idle; no process was stopped.' }
    # Windows venv python.exe may launch another Python process that owns the
    # worker lock. Stop only verified Python descendants, deepest first.
    foreach ($item in @(Get-PlatformWorker | Sort-Object depth -Descending)) {
        $verified = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $item.process.ProcessId) -ErrorAction SilentlyContinue
        if ((Test-PlatformWorkerCommand $verified) -and (Test-PlatformCreationTime $verified $item.process.CreationDate)) {
            Stop-Process -Id $verified.ProcessId -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 250
    if (@(Get-PlatformWorker).Count) { throw 'A verified worker process is still running; no unrelated process was stopped.' }
    Write-Host 'This platform worker stopped; account data was preserved.'
}

switch ($Action) {
    'worker-start' { Start-PlatformWorker }
    'worker-stop' { Stop-PlatformWorker }
    'worker' {
        & $platformPython -u $platformWorker --config $platformConfig
        if ($LASTEXITCODE -ne 0) { throw 'Platform worker ended with an error.' }
    }
    'stop' { Stop-PlatformWorker; Invoke-PlatformManager 'stop' }
    default { Invoke-PlatformManager $Action }
}
