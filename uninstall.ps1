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
    if ($proc -and $proc.CommandLine -match '(shellsrv|server)\.py') {
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

$url = "http://$HostIp/uninstall.sh"
$serverUp = Test-LocalListen -Port 80
$serverOurs = if ($serverUp) { Test-OwnServer -ServerDir $layout.ServerDir } else { $false }
$scriptOk = if ($serverOurs) { Test-Page -Name "uninstall.sh" } else { $false }
$tvUp = Test-TvPort -Tv $TvIp -Port 31337

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
    Say "would run     : $py $($layout.Tools)\root_shell.py `"curl -s http://$HostIp/uninstall.sh | sh`""
    Say "then          : reboot the TV; verify 31337 stays closed"
    exit 0
}

if (-not $tvUp) {
    throw @"
No root channel on TCP 31337 - the TV is off, already unrooted, or the payload failed.
If the TV is rooted only through the browser path, do it manually:
  1. load http://$HostIp/index.html on the TV and leave it
  2. python $($layout.Tools)\kernel_root.py --fork
  3. python $($layout.Tools)\run_root.py "curl -s http://$HostIp/uninstall.sh | sh" 30
  4. reboot the TV
"@
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

$cmd = "curl -s http://$HostIp/uninstall.sh | sh"
if ($KeepBoot) { $cmd = "touch /tmp/keep_boot; " + $cmd }
else { $cmd = "rm -f /tmp/keep_boot; " + $cmd }

Say ""
Say "1) Running the uninstall script on the TV as root..."
$out = & $py (Join-Path $layout.Tools "root_shell.py") $cmd | Out-String
Write-Host $out
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

Say "   channel closed; waiting for the TV to come back..."
$deadline = (Get-Date).AddSeconds($BootTimeoutSec)
while ((Get-Date) -lt $deadline -and -not (Test-Connection -ComputerName $TvIp -Count 1 -Quiet -ErrorAction SilentlyContinue)) {
    Start-Sleep -Seconds 5
}
if (-not (Test-Connection -ComputerName $TvIp -Count 1 -Quiet -ErrorAction SilentlyContinue)) {
    Say "TV did not come back online; run this script again when it is on to verify."
    exit 2
}

Start-Sleep -Seconds 20
if (Test-TvPort -Tv $TvIp -Port 31337) {
    Say "31337 came back after the reboot - uninstall FAILED (payload still active)."
    exit 1
}
Say ""
Say "Uninstall verified: the TV booted with the stock app and 31337 is closed."
exit 0
