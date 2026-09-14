[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('init','build','up','status','stop','start','worker','worker-start','worker-stop','export')]
    [string]$Action
)
$ErrorActionPreference = 'Stop'
$consoleRepo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$consolePython = Join-Path $consoleRepo 'services/peixian-control/.venv/Scripts/python.exe'
$consoleCompose = Join-Path $PSScriptRoot 'compose.console.yaml'
function Invoke-ConsoleCommand([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Console operation failed; existing data was preserved.' }
}
function Get-ConsoleWorker {
    $recordPath = Join-Path $PSScriptRoot '.runtime/console-worker.process.json'
    if (-not (Test-Path -LiteralPath $recordPath)) { return $null }
    $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId = " + [int]$record.pid) -ErrorAction SilentlyContinue
    $scriptPath = Join-Path $PSScriptRoot 'console-worker.py'
    if ($process -and $process.CommandLine -and $process.CommandLine.Contains($scriptPath)) { return $process }
    return $null
}
function Start-ConsoleWorker {
    if (Get-ConsoleWorker) { Write-Host 'Console worker is already running.'; return }
    $runtimePath = Join-Path $PSScriptRoot '.runtime'
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    $workerPath = Join-Path $PSScriptRoot 'console-worker.py'
    $workerProcess = Start-Process -FilePath $consolePython -ArgumentList @('-u',('"' + $workerPath + '"')) -WindowStyle Hidden -WorkingDirectory $consoleRepo -RedirectStandardOutput (Join-Path $runtimePath 'console-worker.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'console-worker.stderr.log') -PassThru
    @{ pid=$workerProcess.Id; script=$workerPath } | ConvertTo-Json | Set-Content -Encoding utf8 -LiteralPath (Join-Path $runtimePath 'console-worker.process.json')
    Start-Sleep -Seconds 2
    if ($workerProcess.HasExited) { throw 'Worker did not start; inspect the local sanitized worker log.' }
    Write-Host ('Console worker started; process ' + $workerProcess.Id)
}
function Stop-ConsoleWorker {
    $workerProcess = Get-ConsoleWorker
    if (-not $workerProcess) { return }
    $check = @'
import json,sys,pathlib,urllib.request
root=pathlib.Path(sys.argv[1])
key=(root/".secrets/console-worker.key").read_text().strip()
request=urllib.request.Request("http://127.0.0.1:14090/internal/worker/busy",headers={"X-Worker-Key":key})
try:
    busy=json.load(urllib.request.urlopen(request,timeout=5)).get("busy",True)
except Exception:
    busy=True
sys.exit(2 if busy else 0)
'@
    & $consolePython -c $check $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Worker may have an active operation; wait for it to finish before stopping.' }
    Stop-Process -Id $workerProcess.ProcessId
    Write-Host 'Console worker stopped. Account data was preserved.'
}
switch ($Action) {
    'init' {
        if (-not (Test-Path $consolePython)) { throw 'Install the isolated control Python environment first; see CONSOLE.md.' }
        Invoke-ConsoleCommand $consolePython @((Join-Path $PSScriptRoot 'console-bootstrap.py'))
    }
    'build' {
        Push-Location $consoleRepo
        try {
            $consoleBun = Join-Path $PSScriptRoot '.runtime/bun-1.3.14/bun-windows-x64/bun.exe'
            if (-not (Test-Path -LiteralPath $consoleBun)) { $consoleBun = 'bun' }
            Push-Location (Join-Path $consoleRepo 'packages/peixian-console')
            try {
                Invoke-ConsoleCommand $consoleBun @('run','typecheck')
                Invoke-ConsoleCommand $consoleBun @('run','build')
            } finally { Pop-Location }
            Invoke-ConsoleCommand 'docker' @('build','-f','services/peixian-control/Gateway.Dockerfile','-t','peixian-gateway:console-r1','.')
            Invoke-ConsoleCommand 'docker' @('build','-f','deploy/peixian/Managed.Dockerfile','-t','peixian-opencode:1.18.30-managed-r1','.')
            Invoke-ConsoleCommand 'docker' @('build','-f','services/peixian-control/Dockerfile','-t','peixian-control:console-r1','.')
        } finally { Pop-Location }
    }
    'up' {
        $listener = Get-NetTCPConnection -State Listen -LocalPort 14090 -ErrorAction SilentlyContinue
        if ($listener) {
            $existing = & docker ps --filter name=^/peixian-console$ --format '{{.Names}}'
            if ($existing -ne 'peixian-console') { throw 'Port 14090 is occupied; no process was stopped.' }
        }
        Invoke-ConsoleCommand 'docker' @('compose','-f',$consoleCompose,'up','-d','--no-build','--pull','never','--wait')
    }
    'status' { Invoke-ConsoleCommand 'docker' @('compose','-f',$consoleCompose,'ps','--all') }
    'stop' { Invoke-ConsoleCommand 'docker' @('compose','-f',$consoleCompose,'stop') }
    'start' { Invoke-ConsoleCommand 'docker' @('compose','-f',$consoleCompose,'up','-d','--no-build','--pull','never','--wait') }
    'worker' { Invoke-ConsoleCommand $consolePython @((Join-Path $PSScriptRoot 'console-worker.py')) }
    'worker-start' { Start-ConsoleWorker }
    'worker-stop' { Stop-ConsoleWorker }
    'export' {
        $consoleExport = Join-Path $PSScriptRoot 'dist/console'
        New-Item -ItemType Directory -Path $consoleExport -Force | Out-Null
        $consoleArchive = Join-Path $consoleExport 'peixian-console-images.tar'
        Invoke-ConsoleCommand 'docker' @('save','-o',$consoleArchive,'peixian-control:console-r1','peixian-gateway:console-r1','peixian-opencode:1.18.30-managed-r1')
        (Get-FileHash -Algorithm SHA256 -LiteralPath $consoleArchive).Hash.ToLower() + '  peixian-console-images.tar' | Set-Content -Encoding ascii -LiteralPath ($consoleArchive + '.sha256')
    }
}
