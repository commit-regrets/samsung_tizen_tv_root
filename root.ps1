<#
.SYNOPSIS
  One-command TV root: start the server, wait for the browser stub, root it,
  deploy the boot payload, then wait for permanent root after the reboot.

.DESCRIPTION
  The only manual steps left are on the TV remote: open the page, then reboot.

    pwsh -File .\root.ps1 -TvIp <tv-ip>

  The script expects tools/ and server/ beside it (or -ToolkitDir). If port 80
  is already served by a different server, pass -RestartServer to replace it.

.PARAMETER TvIp
  TV address (or set ROOT_TV).

.PARAMETER HostIp
  PC address as seen by the TV. Auto-detected from the TV's subnet if omitted.

.PARAMETER ToolkitDir
  Directory containing tools/ and server/.

.PARAMETER Python
  Interpreter for the clients/server. Auto-detected; on Windows a renamed copy
  (pysrv.exe) may be needed for the firewall to allow port 80.

.EXAMPLE
  pwsh -File .\root.ps1 -TvIp 192.168.1.50 -DryRun
#>
[CmdletBinding()]
param(
    [string]$TvIp = $env:ROOT_TV,
    [string]$HostIp,
    [string]$ToolkitDir,
    [string]$Python,
    [string]$Page = "index.html",
    [switch]$NoServer,
    [switch]$RestartServer,
    [switch]$NoWait,
    [switch]$Force,
    [switch]$DryRun,
    [int]$StubWaitSec = 0,
    [int]$BootTimeoutSec = 180
)

$ErrorActionPreference = "Stop"

function Say([string]$m) { Write-Host $m }

function Find-Layout {
    param([string]$Hint)
    $cands = @()
    if ($Hint) { $cands += (Resolve-Path -LiteralPath $Hint).Path }
    $cands += $PSScriptRoot
    foreach ($c in $cands) {
        if (-not $c -or -not (Test-Path -LiteralPath $c)) { continue }
        $c = (Resolve-Path -LiteralPath $c).Path
        $server = Join-Path $c "server\server.py"
        $tools = Join-Path $c "tools"
        $deploy = Join-Path $c "server\deploy.sh"
        if ((Test-Path -LiteralPath $server) -and (Test-Path -LiteralPath $deploy) -and
            (Test-Path -LiteralPath (Join-Path $tools "auto_root.py"))) {
            return [pscustomobject]@{
                Root      = $c
                Server    = $server
                ServerDir = (Split-Path -LiteralPath $server)
                Tools     = $tools
                Deploy    = $deploy
            }
        }
    }
    throw "Toolkit not found: expected tools/ + server/ beside root.ps1 (or pass -ToolkitDir)."
}

function Find-Python {
    param([string]$Explicit)
    if ($Explicit) { return (Resolve-Path -LiteralPath $Explicit).Path }
    if ($env:ROOT_PYTHON) { return $env:ROOT_PYTHON }
    $cmd = Get-Command pysrv.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $base = Join-Path $env:LOCALAPPDATA "Python"
    if (Test-Path -LiteralPath $base) {
        $p = Get-ChildItem -LiteralPath $base -Recurse -Filter pysrv.exe -ErrorAction SilentlyContinue |
             Select-Object -First 1
        if ($p) { return $p.FullName }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "python not found; pass -Python <path>."
}

function Get-LocalAddressFor {
    param([string]$Tv)
    $prefix = (($Tv -split '\.')[0..2]) -join '.'
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Where-Object { $_.IPAddress -like "$prefix.*" -and $_.IPAddress -ne $Tv } |
          Select-Object -First 1 -ExpandProperty IPAddress
    if ($ip) { return $ip }
    return (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' } |
            Select-Object -First 1 -ExpandProperty IPAddress)
}

function Test-TvPort {
    param([string]$Tv, [int]$Port)
    return (Test-NetConnection -ComputerName $Tv -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded
}

function Test-LocalListen {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Test-Page {
    param([string]$Name)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1/$Name" -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-OwnServer {
    # Prove the server on :80 serves *this* directory, not some other copy.
    param([string]$ServerDir)
    $nonce = [guid]::NewGuid().ToString("N")
    $probe = Join-Path $ServerDir ".root_probe"
    try {
        Set-Content -LiteralPath $probe -Value $nonce -Encoding ascii -NoNewline
        $r = Invoke-WebRequest -Uri "http://127.0.0.1/.root_probe" -UseBasicParsing -TimeoutSec 3
        $body = if ($r.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($r.Content) } else { [string]$r.Content }
        return ($body.Trim() -eq $nonce)
    } catch { return $false }
    finally { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
}

function Stop-ToolkitServer {
    $conn = Get-NetTCPConnection -LocalPort 80 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if (-not $conn) { return }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.Name -match 'python|pysrv' -and $proc.CommandLine -match '(shellsrv|server)\.py') {
        Say "server  : stopping pid $($proc.ProcessId) ($($proc.Name))"
        Stop-Process -Id $proc.ProcessId -Force
        Start-Sleep -Milliseconds 600
    } else {
        throw "port 80 is held by $($proc.Name) (pid $($conn.OwningProcess)); refusing to kill it"
    }
}

function Start-ToolkitServer {
    param($Layout, [string]$Py)
    $logDir = Join-Path $Layout.ServerDir "logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $out = Join-Path $logDir "server.out"
    $err = Join-Path $logDir "server.err"
    $p = Start-Process -FilePath $Py -ArgumentList "server.py" -WorkingDirectory $Layout.ServerDir `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(10)
    while (-not (Test-LocalListen -Port 80)) {
        if ((Get-Date) -gt $deadline) { throw "server did not bind :80 (see $err)" }
        Start-Sleep -Milliseconds 250
    }
    Say "server  : pid $($p.Id) listening on :80"
}

if (-not $TvIp) { throw "Pass -TvIp <tv-ip> (or set ROOT_TV)." }

$layout = Find-Layout -Hint $ToolkitDir
$py = Find-Python -Explicit $Python
if (-not $HostIp) { $HostIp = Get-LocalAddressFor -Tv $TvIp }

$url = "http://$HostIp/$Page"
$deployLocal = Join-Path $layout.ServerDir "deploy_local.sh"
$serverUp = Test-LocalListen -Port 80
$serverOurs = if ($serverUp) { Test-OwnServer -ServerDir $layout.ServerDir } else { $false }
$pageOk = if ($serverOurs) { Test-Page -Name $Page } else { $false }
$tvRooted = Test-TvPort -Tv $TvIp -Port 31337

Say "=== TV root ==============================================="
Say "toolkit : $($layout.Root)"
Say "python  : $py"
Say "TV      : $TvIp"
Say "host    : $HostIp"
Say "page    : $url"
if ($DryRun) { Say "mode    : DRY RUN" }
Say "==========================================================="

if ($DryRun) {
    Say ""
    if (-not $serverUp) {
        Say "server on :80 : not listening (would start $($layout.Server))"
    } elseif ($serverOurs -and $pageOk) {
        Say "server on :80 : this toolkit's server (would reuse)"
    } elseif ($serverOurs) {
        Say "server on :80 : this toolkit, but /$Page is not 200"
    } else {
        Say "server on :80 : a DIFFERENT server (would need -RestartServer)"
    }
    Say "31337 on TV   : $(if ($tvRooted) { 'open (TV looks rooted)' } else { 'closed' })"
    Say "would write   : $deployLocal"
    Say "would run     : $py $($layout.Tools)\auto_root.py --host $HostIp --script deploy_local.sh --stub-wait $StubWaitSec --root-retries 3"
    Say "then wait     : 31337 for up to $BootTimeoutSec s after the reboot"
    exit 0
}

if (-not (Test-Connection -ComputerName $TvIp -Count 1 -Quiet -ErrorAction SilentlyContinue)) {
    Say "warning : the TV does not answer ping; continuing anyway"
}

if ($tvRooted -and -not $Force) {
    Say ""
    Say "Port 31337 is already open - this TV is rooted."
    Say "Use -Force to check/redeploy anyway (you will need the TV remote to load the page)."
    exit 0
}

if ($NoServer) {
    if (-not ($serverOurs -and $pageOk)) { throw "-NoServer given but this toolkit's /$Page is not served on :80" }
    Say "server  : using the existing server (-NoServer)"
} elseif ($serverUp -and $RestartServer) {
    # always restart on request: clears stale RPC waiters from earlier runs
    Stop-ToolkitServer
    Start-ToolkitServer -Layout $layout -Py $py
} elseif ($serverUp -and $serverOurs -and $pageOk) {
    Say "server  : reusing the server on :80"
} elseif ($serverUp) {
    throw "port 80 is served by another server. Re-run with -RestartServer to replace it."
} else {
    Start-ToolkitServer -Layout $layout -Py $py
}

if (-not (Test-Page -Name $Page)) { throw "server is not serving /$Page after start" }

$text = Get-Content -LiteralPath $layout.Deploy -Raw
$text = [regex]::Replace($text, '(?m)^H=.*$', "H=http://$HostIp")
$text = $text -replace "`r`n", "`n"

# The stub runs as uid 5001 with the BROWSER's SMACK label, and that label cannot
# write the app's bin/ - only the app's own label can (docs/FAILED.md). By the time
# this script runs, auto_root.py has already patched the stub's cred to uid 0 with
# full caps, so the shell it forks is root and CAN take the app's label. Inject
# that here, otherwise the deploy ends in COPY=fail.
$prelude = @'
# --- injected by root.ps1: take the app's label so bin/ is writable ------------
_APPID_LABEL=User::Pkg::com.samsung.tv.MultiControl-Service
echo -n "$_APPID_LABEL" > /proc/self/attr/current 2>/dev/null
if [ "$(cat /proc/self/attr/current 2>/dev/null)" = "$_APPID_LABEL" ]; then
  echo RELABEL=ok
else
  echo "RELABEL=fail uid=$(id -u) - the deploy below will fail; use server/recover.sh from a root shell"
fi
# ------------------------------------------------------------------------------
'@
$prelude = $prelude -replace "`r`n", "`n"
if ($text -match '(?s)^(#!/[^\n]*\n)') {
    $text = $Matches[1] + $prelude + "`n" + $text.Substring($Matches[1].Length)
} else {
    $text = $prelude + "`n" + $text
}
[IO.File]::WriteAllText($deployLocal, $text, [Text.Encoding]::ASCII)

Say ""
Say "1) ON THE TV, with its remote, open this URL:"
Say ""
Say "     $url"
Say ""
Say "   Wait until the page shows RUNNING, then leave it in the foreground."
Say "   The script CANNOT open the TV browser for you - it is waiting now,"
Say "   and will remind you every 30 s if the page has not connected."
Say "   If a stub dies during root, it will ask you to RELOAD the page once"
Say "   and then continues automatically (up to 3 fresh stubs)."
Say ""
& $py (Join-Path $layout.Tools "auto_root.py") --host $HostIp --script "deploy_local.sh" `
    --wait 150 --stub-wait $StubWaitSec --page $Page --heartbeat 30 --root-retries 3
if ($LASTEXITCODE -ne 0) {
    Say ""
    Say "Deploy failed (exit $LASTEXITCODE)."
    Say "- if the page was never opened, open $url on the TV and run again"
    Say "- if it was opened, reload it once and run again (the stub may have died)"
    Say "- see docs/FAILED.md for the stub traps"
    exit 1
}

Say ""
Say "2) Deploy verified (the payload md5 matched)."
Say "   NOTE: deploy.sh kill -9s the running payload so AUL loads the new DLL;"
Say "   31337 can open WITHOUT a reboot. That proves the payload runs, not that"
Say "   it starts at boot - only a reboot proves persistence."
if ($NoWait) { exit 0 }

Say "   waiting for TCP 31337 (up to $BootTimeoutSec s)..."
$deadline = (Get-Date).AddSeconds($BootTimeoutSec)
$up = $false
while ((Get-Date) -lt $deadline) {
    if (Test-TvPort -Tv $TvIp -Port 31337) { $up = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $up) {
    Say "31337 did not come up within $BootTimeoutSec s."
    Say "Check the beacon log ($($layout.ServerDir)\logs\beacons.log), then run:"
    Say "  $py $($layout.Tools)\root_shell.py `"id`" $TvIp"
    exit 1
}
Say ""
Say "31337 is up (restarted app). Now REBOOT the TV with the browser closed, then verify:"
Say "  $py $($layout.Tools)\root_shell.py `"id`" $TvIp"
exit 0
