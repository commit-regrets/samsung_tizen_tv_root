# Boot-persistence regression — root cause and fix

**Status: resolved (2026-10-22, payload v10 era).** The app was being launched at
every boot; it exited before
`Main` because our payload DLL carried the wrong SMACK label. The fix is in
`deploy.sh` and `uninstall.sh`, and both verify it on every run. This document is
kept because the diagnosis was wrong for a long time and the mechanism is subtle.
Evidence blocks and deploy output below are from that era (sizes, beacon shapes
and the label-check placement have since evolved - `AGENTS.md` is current).

## TL;DR

The app was **never** failing to be launched. AUL launched it at every boot
(four attempts are in the kernel audit log) and the process **exited before
`Main`** because the .NET host was denied read access to its own assembly:

```
lsm=SMACK fn=smack_inode_getattr action=denied mode=enforcing
subject="User::Pkg::com.samsung.tv.MultiControl-Service"
object ="User::Pkg::org.tizen.browser"      requested=r
path=".../bin/MultiControlService.dll" comm="MultiControlSer"
```

`MultiControlService.dll` is our payload. It was written by the **browser stub**,
so the new file kept the **browser's** SMACK label. The app runs under its own
label, cannot read a file labelled for the browser, and the runtime dies
immediately — before the first `Beacon`, which is why an earlier session saw "no
beacons" and concluded "AUL didn't start it".

Fix: give the DLL the app's own label (`chsmack -a
'User::Pkg::com.samsung.tv.MultiControl-Service::RO' <dll>`), and make
`deploy.sh` / `uninstall.sh` do it every time (they do, and verify it).

## Why it only broke after the uninstall test

Nothing about the uninstall itself. It is about **who does the copy**:

| deploy source | process label | label inherited by the DLL | app starts? |
|---|---|---|---|
| the app's own root channel (31337) | `User::Pkg::com.samsung.tv.MultiControl-Service` | correct | yes |
| the browser stub | `User::Pkg::org.tizen.browser` | wrong | **no** |

A file created by `cp`/`mv` takes the **writing process's** SMACK label. Deploy
from the app's own channel and the label is right by construction; deploy from the
browser and it is wrong. That single difference explains the whole
"boot-persistence regression".

## Evidence

1. `aulctl list-apps 5001` — the app is in AUL's boot list:
   ```
   5001 user boot sequence app list
   com.samsung.tv.health-mde-service
   com.samsung.tv.MultiControl-Service
   ```
2. `aulctl status com.samsung.tv.MultiControl-Service` at boot:
   ```
   status: active   sub status: exited
   begin: 1:0:3     end: 1:0:3     terminated time: <boot+seconds>
   ```
3. Kernel audit, one denial per boot attempt:
   ```
   subject="User::Pkg::com.samsung.tv.MultiControl-Service"
   object="User::Pkg::org.tizen.browser" requested=r
   path=".../MultiControlService.dll" comm="MultiControlSer"
   send signal SIG : 6, MultiControlSer -> handler: send_signal_ratelimited
   ```
4. Labels before/after (only `ls -Z` shows the label):
   ```
   before: MultiControlService.dll -> User::Pkg::org.tizen.browser
   siblings: MultiControlService, .pdb, .runtimeconfig.json
             -> User::Pkg::com.samsung.tv.MultiControl-Service::RO
   after : MultiControlService.dll -> User::Pkg::com.samsung.tv.MultiControl-Service::RO
   ```

## Fix, verified

`deploy.sh` now, right after the DLL is in place:

```sh
chsmack -a "$WANT_LABEL" "$D" 2>/dev/null
GOT_LABEL=$(ls -lZ "$D" | awk '{for(i=1;i<=NF;i++) if ($i ~ /^User::|^System::|^_$/) {print $i; exit}}')
echo "DLL_LABEL=$GOT_LABEL"
[ "$GOT_LABEL" = "$WANT_LABEL" ] || echo DLL_LABEL_MISMATCH
```

with `WANT_LABEL="User::Pkg::$APPID::RO"`. `uninstall.sh` relabels the stock IL
and NI files it copies back, for the same reason. (Later hardening moved the
label-and-verify one step earlier: current `deploy.sh` labels and verifies the
*temp* DLL before the rename, so a wrong label aborts with the live DLL
untouched - `AGENTS.md` §9.)

Live deploy over the root channel (payload v10):

```
DEPLOY_START / UID=0 / SIZE=20480 / COPY=ok
DLL_LABEL=User::Pkg::com.samsung.tv.MultiControl-Service::RO
AOT=disabled / ALLOW=<pc-ip> / HOST_FILE=<pc-ip>
BOOT_ROW=ok / BOOT_ROW_COUNT=1 / AUL_RELOAD=ok
RESTART=backgrounded / DEPLOY_DONE
```

First cold boot after the fix, from the server beacon log:

```
DSHROOT start uid=5001 pid=<pid>
DSHROOT kernel=20008000 init_task=c0957180
DSHROOT round=0 pre=0
DSHROOT tail: per/0,per/0,...            <- the corrupted list, as the app sees it
DSHROOT child=d1aea840 self=c877ae00     <- self found via the child's parent pointer
DSHROOT self cred=df9fda80 real=df9fda80
DSHROOT self-patch uid=0
DSHROOT SUCCESS-R00T ...
DSHROOT device closed
DSHROOT ROOTCHAN 31337 uid=0
```

and from the PC:

```
$ python tools\root_shell.py "id"
uid=0(root) ... context="User::Pkg::com.samsung.tv.MultiControl-Service"
```

Note the context: the channel runs under the **app's** label, which can read the
app's own files.

Restart path also verified: `kill -9 <payload pid>` → AUL restarts the app → it
re-roots and 31337 is back within seconds.

## Tooling facts learned the hard way

* **`op 7` (RUN) is one-shot per stub.** The first `fork+execve("/bin/sh")` works
  and the stub still serves physmap afterwards; a second `op 7` on the same stub
  times out and the stub is then useless. Plan one shell batch per page load.
* **`fork()` copies the cred.** Patching a forked child's cred roots nothing — the
  cred that matters is the one the RPC thread itself uses. Find the parent through
  the child's `real_parent` and patch that.
* **The task list is damaged on this kernel, repeatedly, within seconds of boot.**
  `init.tasks.prev` dies at hop 5–17 with a non-pointer; the app's own walk shows
  twenty `per/0` entries. Freshly allocated task_structs often read back as `0xff`
  fill or stale bytes, so a comm-based match can fail even when the address is
  right. Reading `init.tasks.prev` **immediately after a fork** works, because our
  child is at the head — that is the reliable locator.
* **List-independent root that works every time:** scan for the cred pattern. An
  owner `struct cred` holds `ids = (5001,100,5001,100,5001,100,5001,100)` at
  `cred+4` — 32 bytes that do not occur by accident. Scan lowmem for it, check the
  refcount at `cred`, skip implausible values, patch. `tools/scan_cred.py` patched
  253 creds in one pass and the next shell came back `uid=0`.
* **Where things live:** creds and task_structs sit in phys `0x20000000`–
  `0x40000000` on this unit. Do **not** scan past `0x46000000`: two full scans
  hung there, so the scan is bounded to `0x40000000`.
* **`ls` on this Tizen only prints the SMACK label with `-Z`.** A label check
  without `-Z` reads an empty string — that is how a deploy can look green and
  still produce an unlaunchable app. `chsmack <path>` with no options also prints
  it (`access=... transmute=...`).
* **`chsmack` works without CAP_MAC_ADMIN when the file's current label equals the
  caller's** (relabel your own object).
* **Relabelling *ourselves* does work, with root and full caps.**
  `echo -n "User::Pkg::<appid>" > /proc/self/attr/current` succeeds for a task
  whose cred is uid 0 with all capabilities — measured repeatedly, and it is what
  reinstalled the payload after the uninstall test. An earlier conclusion in this
  document said the write is always denied by `smack_onlycap`; that was **wrong**
  (the shell it was tried from did not have the patched cred). Always retest.
  `smack_onlycap` does restrict capability bypass to labelled subjects, so do not
  assume a capability alone is enough.
* **The browser's label cannot read the app's `bin/`** even as uid 0, and no
  policy rule grants it. Use the app's label, or the app's own channel.
* **The server must prefer a freshly queued stub** over the current one: a wedged
  stub otherwise blocks every later attempt. `server/server.py` takes a queued
  fresh stub in preference, and `physmap.reset_stub()` sends an `RSET` sentinel to
  drop a dead pairing without restarting anything.
* **A hard power-off leaves a zombie socket** (no FIN). `RSET` clears it; that is
  what the sentinel exists for.

## Where this left things

All of it is done and verified: the script fixes are in the repo, the uninstall
path was re-run end to end (stock restored, boot row verified gone, channel stayed
closed after reboot), and the payload was reinstalled and confirmed on cold boots.
The pid-hash/IDR locator remains blocked, and no longer matters — the cred-pattern
scan replaced it. See `docs/CHANGELOG-ARCHIVE.md` (2026-10-22 entries) for the
sequence and `AGENTS.md` for the current procedure.
