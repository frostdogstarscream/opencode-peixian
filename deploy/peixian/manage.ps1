[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('init', 'build', 'up', 'stop', 'start', 'restart', 'recreate', 'status', 'verify', 'export')]
    [string]$Action,
    [ValidateSet('all', 'client-a', 'client-b')]
    [string]$Client = 'all',
    [string]$Python = 'python',
    [switch]$Lifecycle,
    [switch]$StartDocker
)

$ErrorActionPreference = 'Stop'
$deployRoot = $PSScriptRoot
$composePath = Join-Path $deployRoot 'compose.yaml'
$secretRoot = Join-Path $deployRoot '.secrets'
$venvPython = Join-Path $deployRoot '.venv\Scripts\python.exe'
$imageName = 'peixian-opencode:1.18.30-r1'
$projectName = 'peixian-opencode'

# The optional live-model profile has its own Compose overlay and acceptance.
if (Test-Path -LiteralPath (Join-Path $deployRoot '.runtime/deepseek.enabled')) {
    if ($Action -eq 'build') { throw 'Disable the DeepSeek profile before rebuilding the baseline image.' }
    if ($Action -ne 'init') {
        $profileAction = $Action
        if ($profileAction -eq 'up') { $profileAction = 'start' }
        & (Join-Path $deployRoot 'deepseek.ps1') -Action $profileAction -Client $Client
        exit $LASTEXITCODE
    }
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE)." }
}

function Invoke-Compose {
    param([string[]]$Arguments)
    Invoke-Checked 'docker' (@('compose', '--project-name', $projectName, '--file', $composePath) + $Arguments)
}

function Assert-Docker {
    $dockerReady = & docker info --format '{{.OSType}}' 2>$null
    if ($LASTEXITCODE -eq 0 -and $dockerReady -eq 'linux') { return }
    if (-not $StartDocker) { throw 'Docker Linux engine is unavailable. Start Docker Desktop, then retry (or use -StartDocker).' }
    $desktopExe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path -LiteralPath $desktopExe)) { throw 'Docker Desktop executable was not found.' }
    Start-Process -FilePath $desktopExe -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        $dockerReady = & docker info --format '{{.OSType}}' 2>$null
        if ($LASTEXITCODE -eq 0 -and $dockerReady -eq 'linux') { return }
    }
    throw 'Docker Linux engine did not become available. No containers or data were reset.'
}

function Read-ClientPassword {
    param([string]$Name)
    $secretPath = Join-Path $secretRoot "$Name.password"
    if (-not (Test-Path -LiteralPath $secretPath -PathType Leaf)) { throw "Missing password file for $Name. Run manage.ps1 -Action init first." }
    $value = [System.IO.File]::ReadAllText($secretPath).TrimEnd([char[]]@([char]13, [char]10))
    if ($value.Length -lt 16 -or $value.IndexOfAny([char[]]@([char]13, [char]10, [char]0)) -ge 0) {
        throw "Invalid password file for $Name. Use one line with at least 16 characters."
    }
    return $value
}

function Initialize-Secrets {
    if (-not (Test-Path -LiteralPath $secretRoot)) {
        New-Item -ItemType Directory -Path $secretRoot | Out-Null
    }
    # Restrict secret files to this Windows identity and SYSTEM; do not change parent ACLs.
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $secretAcl = New-Object System.Security.AccessControl.DirectorySecurity
    $secretAcl.SetOwner($currentSid)
    $secretAcl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($currentSid, $systemSid)) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $secretAcl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $secretRoot -AclObject $secretAcl
    foreach ($name in @('client-a', 'client-b')) {
        $secretPath = Join-Path $secretRoot "$name.password"
        if (Test-Path -LiteralPath $secretPath) {
            $null = Read-ClientPassword $name
            continue
        }
        $bytes = New-Object byte[] 48
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        [System.IO.File]::WriteAllText($secretPath, [Convert]::ToBase64String($bytes), (New-Object System.Text.UTF8Encoding($false)))
    }
    Write-Host 'Per-client credentials are ready in .secrets. Values are not printed.'
}

function Assert-Secrets {
    $passwordA = Read-ClientPassword 'client-a'
    $passwordB = Read-ClientPassword 'client-b'
    if ($passwordA -ceq $passwordB) { throw 'Client passwords must differ.' }
}

function Read-Evidence {
    param([string]$Name)
    $reportPath = Join-Path $deployRoot "evidence\$Name.json"
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw "Required evidence is missing: $Name" }
    return Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
}

function Assert-ExportEvidence {
    $imageJson = & docker image inspect $imageName --format '{{json .}}'
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the image to export.' }
    $image = $imageJson | ConvertFrom-Json
    if ($image.Id -notmatch '^sha256:[0-9a-f]{64}$' -or $image.Os -ne 'linux' -or $image.Architecture -ne 'amd64') {
        throw 'The export image must be an inspected linux/amd64 image.'
    }
    $composeHash = (Get-FileHash -LiteralPath $composePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $report = Read-Evidence 'api-isolation'
    if ($report.status -ne 'passed' -or $report.lifecycle_completed -ne $true -or $report.compose_sha256 -cne $composeHash) {
        throw 'Current API, isolation, and lifecycle verification must pass for this Compose file before export.'
    }
    foreach ($name in @('client-a', 'client-b', 'client-a-entry', 'client-b-entry')) {
        $runtime = $report.runtime.$name
        if ($runtime.image_id -cne $image.Id -or $runtime.platform -cne 'linux/amd64') {
            throw "The current image was not verified for $name. Rerun acceptance."
        }
    }
    foreach ($name in @('browser', 'cold-start')) {
        $evidence = Read-Evidence $name
        if ($evidence.status -ne 'passed' -or $evidence.image_id -cne $image.Id -or $evidence.compose_sha256 -cne $composeHash) {
            throw "Current $name verification must pass for this image and Compose file before export."
        }
    }
    return $image.Id
}

function Assert-Ports {
    $selected = @('client-a', 'client-b')
    if ($Client -ne 'all') { $selected = @($Client) }
    foreach ($name in $selected) {
        $port = 14091
        if ($name -eq 'client-b') { $port = 14092 }
        # The per-client entry publishes the port; the isolated agent has no host bindings.
        $entryService = "$name-entry"
        $owned = @(& docker ps --filter "label=com.docker.compose.project=$projectName" --filter "label=com.docker.compose.service=$entryService" --format '{{.ID}}')
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect existing project entry containers.' }
        if ($owned.Count -gt 1) { throw "Multiple running containers claim entry service $entryService. Existing processes were left intact." }
        if ($owned.Count -eq 1) {
            $publishedJson = & docker inspect --format '{{json .HostConfig.PortBindings}}' $owned[0]
            if ($LASTEXITCODE -ne 0) { throw "Could not inspect published ports for $entryService." }
            $published = $publishedJson | ConvertFrom-Json
            $matching = @($published.'4096/tcp' | Where-Object { $_.HostIp -eq '127.0.0.1' -and $_.HostPort -eq [string]$port })
            if ($matching.Count -eq 1) { continue }
        }
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        try { $listener.Start() }
        catch { throw "Port $port is already occupied. Existing processes were left intact." }
        finally { $listener.Stop() }
    }
}

function Initialize-Python {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Checked $Python @('-m', 'venv', (Join-Path $deployRoot '.venv'))
    }
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', (Join-Path $deployRoot 'requirements.txt'))
}

$targets = @()
if ($Client -ne 'all') { $targets = @($Client) }

if ($Action -eq 'init') {
    Initialize-Secrets
    Assert-Secrets
    Initialize-Python
    exit 0
}

Assert-Docker
if ($Action -ne 'status' -and $Action -ne 'stop') { Assert-Secrets }

switch ($Action) {
    'build' {
        Invoke-Compose @('config', '--quiet')
        Invoke-Compose @('build', 'client-a')
    }
    'up' {
        Assert-Ports
        Invoke-Compose (@('up', '-d', '--wait', '--wait-timeout', '180') + $targets)
    }
    'stop' { Invoke-Compose (@('stop', '--timeout', '30') + $targets) }
    'start' {
        Assert-Ports
        Invoke-Compose (@('up', '-d', '--wait', '--wait-timeout', '180') + $targets)
    }
    'restart' { Invoke-Compose (@('restart', '--timeout', '30') + $targets) }
    'recreate' {
        Assert-Ports
        Invoke-Compose (@('up', '-d', '--force-recreate', '--no-deps', '--wait', '--wait-timeout', '180') + $targets)
    }
    'status' { Invoke-Compose @('ps') }
    'verify' {
        if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run manage.ps1 -Action init first.' }
        $verifyArgs = @((Join-Path $deployRoot 'verify.py'))
        if ($Lifecycle) { $verifyArgs += '--lifecycle' }
        Invoke-Checked $venvPython $verifyArgs
    }
    'export' {
        if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { throw 'Run manage.ps1 -Action init first.' }
        $currentImageId = Assert-ExportEvidence
        $outputRoot = Join-Path $deployRoot 'dist'
        New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
        $imagePath = Join-Path $outputRoot 'peixian-opencode-1.18.30-r1-linux-amd64.tar'
        # Preserve the tag required by offline Compose; package.py verifies the saved image content.
        Invoke-Checked 'docker' @('image', 'save', '--output', $imagePath, $imageName)
        if ((Assert-ExportEvidence) -cne $currentImageId) { throw 'The image changed during export; rerun acceptance and export.' }
        $imageHash = (Get-FileHash -LiteralPath $imagePath -Algorithm SHA256).Hash.ToLowerInvariant()
        [System.IO.File]::WriteAllText("$imagePath.sha256", "$imageHash  $([System.IO.Path]::GetFileName($imagePath))`n", (New-Object System.Text.UTF8Encoding($false)))
        $wheelRoot = Join-Path $outputRoot 'wheels'
        New-Item -ItemType Directory -Path $wheelRoot -Force | Out-Null
        Invoke-Checked $venvPython @('-m', 'pip', 'download', '--only-binary=:all:', '--dest', $wheelRoot, '-r', (Join-Path $deployRoot 'requirements.txt'))
        Invoke-Checked $venvPython @((Join-Path $deployRoot 'package.py'), '--image-id', $currentImageId)
        Write-Host "Image exported to $imagePath"
    }
}
