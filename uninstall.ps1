<#
.SYNOPSIS
  Undo the root: restore the stock MultiControl-Service app on the TV.

.DESCRIPTION
  Talks to the TV's root channel (TCP 31337), runs server/uninstall.sh as root,
  then waits for the reboot and verifies the channel does not come back.

  What it restores:
    - bin/MultiControlService.dll  <- share/mcs_orig.dll  (stock IL)
    - bin/.native_image/           <- share/mcs_ni_orig.dll (stock AOT)
    - deletes our boot_sequence row from .appsvc.db (unless -KeepBoot)
    - deletes share/payload_backup.dll and our /tmp leftovers

.PARAMETER TvIp
  TV address (or set ROOT_TV).

.PARAMETER KeepBoot
  Keep the boot_sequence row (the app still starts at boot, but as stock).

.EXAMPLE
  pwsh -File .\uninstall.ps1 -TvIp 192.168.1.50 -DryRun
#>
[CmdletBinding()]
param(
    [string]$TvIp = $env:ROOT_TV,
    [string]$HostIp,
    [string]$ToolkitDir,
    [string]$Python,
    [switch]$KeepBoot,
    [switch]$NoServer,
    [switch]$RestartServer,
    [switch]$DryRun,
    [switch]$NoWait,
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
        $script = Join-Path $c "server\uninstall.sh"
        if ((Test-Path -LiteralPath $server) -and (Test-Path -LiteralPath $script) -and
            (Test-Path -LiteralPath (Join-Path $tools "root_shell.py"))) {
            return [pscustomobject]@{
                Root      = $c
                Server    = $server
                ServerDir = (Split-Path -LiteralPath $server)
                Tools     = $tools
                Uninstall = $script
            }
        }
    }
    throw "Toolkit not found: expected tools/ + server/ beside uninstall.ps1 (or pass -ToolkitDir)."
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
    # Route-first, like root.ps1: the "first non-loopback" fallback can hand the
    # TV a VPN address (review finding M5, 2026-10-26).
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

function Test-StockTv {
    # "The TV came back" = a stock Samsung service answers TCP.  There is no
    # ICMP alternative: ping cannot decide this on this PC (VPN tunnel error
    # replies count as 0% loss; a proxy-ARP router answers for an offline set).
    # HONESTY NOTE: none of these four ports is MEASURED on this set - if the
    # model serves none of them, the caller treats silence as "not confirmed"
    # (conservative exit 2), never as proof the TV is down.
    param([string]$Tv)
    foreach ($p in 8001, 8002, 7676, 9197) {
        if (Test-TvPort -Tv $Tv -Port $p) { return $true }
    }
    return $false
}

function Test-LocalListen {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return $false }
    # A loopback-only listener cannot serve the TV; do not count it as "up".
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

$url = "http://$HostIp/uninstall.sh"
$serverUp = Test-LocalListen -Port 80
$serverOurs = if ($serverUp -and -not $DryRun) { Test-OwnServer -ServerDir $layout.ServerDir } else { $false }
$scriptOk = if ($serverOurs) { Test-Page -Name "uninstall.sh" } else { $false }
$tvUp = Test-TvPort -Tv $TvIp -Port 31337
$cmdPreview = "curl -s http://$HostIp/uninstall.sh | sh"
if ($KeepBoot) { $cmdPreview = "touch /tmp/keep_boot; " + $cmdPreview }
else { $cmdPreview = "rm -f /tmp/keep_boot; " + $cmdPreview }

Say "=== TV uninstall =========================================="
Say "toolkit : $($layout.Root)"
Say "python  : $py"
Say "TV      : $TvIp"
Say "host    : $HostIp"
Say "script  : $url"
Say "boot row: $(if ($KeepBoot) { 'keep' } else { 'remove' })"
if ($DryRun) { Say "mode    : DRY RUN" }
Say "==========================================================="

if ($DryRun) {
    Say ""
    if (-not $serverUp) {
        Say "server on :80 : not listening (would start $($layout.Server))"
    } elseif ($serverOurs -and $scriptOk) {
        Say "server on :80 : this toolkit's server (would reuse)"
    } else {
        Say "server on :80 : a DIFFERENT server / no uninstall.sh (would need -RestartServer)"
    }
    Say "31337 on TV   : $(if ($tvUp) { 'open (can uninstall)' } else { 'closed (TV off, or already unrooted)' })"
    Say "would run     : $py $($layout.Tools)\root_shell.py `"$cmdPreview`" $TvIp"
    Say "then          : reboot the TV; verify 31337 stays closed"
    exit 0
}

if ($NoServer) {
    if (-not ($serverOurs -and $scriptOk)) { throw "-NoServer given but /uninstall.sh is not served on :80" }
} elseif ($serverUp -and $serverOurs -and $scriptOk) {
    Say "server  : reusing the server on :80"
} elseif ($serverUp) {
    if (-not $RestartServer) {
        throw "port 80 is served by another server. Re-run with -RestartServer to replace it."
    }
    Stop-ToolkitServer
    Start-ToolkitServer -Layout $layout -Py $py
} else {
    Start-ToolkitServer -Layout $layout -Py $py
}
if (-not (Test-Page -Name "uninstall.sh")) { throw "server is not serving /uninstall.sh after start" }

# Reaching here means the server is genuinely serving the script, so the manual
# recovery instructions below can be followed as printed (the old code threw
# before starting it and told the operator to load a page nothing served).
if (-not $tvUp) {
    throw @"
No root channel on TCP 31337 - the TV is off, already unrooted, or the payload failed.
The server IS running and serving http://$HostIp/index.html.
If the TV is rooted only through the browser path, do it manually:
  1. load http://$HostIp/index.html on the TV and leave it
  2. python $($layout.Tools)\kernel_root.py --fork
  3. python $($layout.Tools)\run_root.py "curl -s http://$HostIp/uninstall.sh | sh" 30
  4. reboot the TV
"@
}

$cmd = $cmdPreview

Say ""
Say "1) Running the uninstall script on the TV as root..."
$env:ROOT_SHELL_TIMEOUT = "180"   # uninstall.sh is several steps; reply at __END__
$out = & $py (Join-Path $layout.Tools "root_shell.py") $cmd $TvIp | Out-String
Write-Host $out
if ($LASTEXITCODE -ne 0) {
    Say "root_shell.py failed (exit $LASTEXITCODE) - is the TV still rooted and on the LAN?"
    exit 1
}
if ($out -notmatch "UNINSTALL_DONE") {
    Say "The TV did not report UNINSTALL_DONE - stock app not restored."
    exit 1
}

Say "2) Stock app restored. Reboot the TV now (Home/Exit, then power-cycle)."
if ($NoWait) { exit 0 }

Say "   waiting for 31337 to close (up to $BootTimeoutSec s)..."
$deadline = (Get-Date).AddSeconds($BootTimeoutSec)
while ((Get-Date) -lt $deadline -and (Test-TvPort -Tv $TvIp -Port 31337)) { Start-Sleep -Seconds 5 }
if (Test-TvPort -Tv $TvIp -Port 31337) {
    Say "31337 is still open - the app is still running the payload. Reboot and re-run to verify."
    exit 1
}

Say "   channel closed; waiting for a stock TV service to answer (up to $BootTimeoutSec s)..."
$deadline = (Get-Date).AddSeconds($BootTimeoutSec)
while ((Get-Date) -lt $deadline -and -not (Test-StockTv -Tv $TvIp)) {
    Start-Sleep -Seconds 5
}
if (-not (Test-StockTv -Tv $TvIp)) {
    Say "TV did not come back online; run this script again when it is on to verify."
    Say "(decided by TCP probes of 8001/8002/7676/9197 - ping is not evidence on this PC,"
    Say " a VPN tunnel's ICMP errors count as replies; see AGENTS.md section 8, ICMP trap)"
    Say "(none of those ports is measured on this set - if this fires while the TV is"
    Say " clearly on, record which ports it serves and update Test-StockTv)"
    exit 2
}

Start-Sleep -Seconds 20
# The payload takes ~40 s from boot to open 31337, so a single 20 s look can call
# a still-booting payload "gone".  Watch for the rest of the boot budget instead:
# a stock app must never open it, at any point in this window.
$settle = (Get-Date).AddSeconds([Math]::Max(60, $BootTimeoutSec))
while ((Get-Date) -lt $settle) {
    if (Test-TvPort -Tv $TvIp -Port 31337) {
        Say "31337 came back after the reboot - uninstall FAILED (payload still active)."
        exit 1
    }
    Start-Sleep -Seconds 5
}
if (Test-TvPort -Tv $TvIp -Port 31337) {
    Say "31337 came back after the reboot - uninstall FAILED (payload still active)."
    exit 1
}
Say ""
Say "Uninstall verified: the TV booted with the stock app and 31337 stayed closed."
exit 0
