# Boot-persistence regression — ROOT CAUSE AND FIX (2026-10-22 15:55)

**Status: RESOLVED. The TV is rooted again, root returns by itself at every
boot, and 31337 is up.** This supersedes the "UNROOTED" state in
`HANDOVER-2026-10-22-UNROOTED.md`.

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

`MultiControlService.dll` is our payload. It was written by the **browser
stub**, so the new file kept the **browser's** SMACK label. The app runs under
its own label, cannot read a file labelled for the browser, and the runtime
dies immediately — before the first `Beacon`, which is why the previous session
saw "no beacons" and concluded "AUL didn't start it".

Fix: give the DLL the app's own label (`chsmack -a
'User::Pkg::com.samsung.tv.MultiControl-Service::RO' <dll>`), and make
`deploy.sh` / `uninstall.sh` do it every time (they now do, and verify it).

## Why it only broke after the uninstall test

Nothing about the uninstall itself. It is about **who does the copy**:

| deploy source | process label | label inherited by the DLL | app starts? |
|---|---|---|---|
| v5/v6 era: the app's own root channel (31337) | `User::Pkg::com.samsung.tv.MultiControl-Service` | correct | yes |
| after the uninstall: the browser stub | `User::Pkg::org.tizen.browser` | wrong | **no** |

A file created by `cp`/`mv` takes the **writing process's** SMACK label. Deploy
from the app's own channel and the label is right by construction; deploy from
the browser and it is wrong. That single difference explains the whole
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
   begin: 1:0:3     end: 1:0:3     terminated time: 14:58:12
   ```
3. Kernel audit, one denial per boot attempt (4 attempts on that boot):
   ```
   subject="User::Pkg::com.samsung.tv.MultiControl-Service"
   object="User::Pkg::org.tizen.browser" requested=r
   path=".../MultiControlService.dll" comm="MultiControlSer"
   send signal SIG : 6, MultiControlSer -> handler: send_signal_ratelimited
   ```
4. Labels before/after (this `ls` only shows the label with `-Z`):
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
and NI files it copies back, for the same reason.

Live deploy over the root channel:

```
DEPLOY_START / UID=0 / SIZE=18432 / COPY=ok   (v7 at the time; current payload is v9, see AGENTS.md)
DLL_LABEL=User::Pkg::com.samsung.tv.MultiControl-Service::RO
ALLOW=192.168.178.214 / BOOT_ROW=ok / AUL_RELOAD=ok / DEPLOY_DONE
```

First cold boot after the fix, from the server beacon log:

```
DSHROOT start uid=5001 pid=6162
DSHROOT kernel=20008000 init_task=c0957180
DSHROOT round=0 pre=0
DSHROOT tail: per/0,per/0,...            <- the corrupted list, as the app sees it
DSHROOT child=d1aea840 self=c877ae00     <- v7 finds self via the child's parent pointer
DSHROOT self cred=df9fda80 real=df9fda80
DSHROOT self-patch uid=0
DSHROOT SUCCESS-R00T ...
DSHROOT device closed
DSHROOT ROOTCHAN 31337 uid=0
```

and from the PC:

```
$ python recon/chan.py "id"
uid=0(root) ... context="User::Pkg::com.samsung.tv.MultiControl-Service"
```

Note the context: the channel now runs under the **app's** label (better than the
browser label — it can read the app's own files).

Restart path also verified: `kill -9 <payload pid>` → AUL restarts the app →
it re-roots and 31337 is back.

## Tooling facts learned the hard way (keep these)

* **`op 7` (RUN) is one-shot per stub.** The first `fork+execve("/bin/sh")`
  works and the stub still serves physmap afterwards; a second `op 7` on the
  same stub times out and the stub is then useless. Plan one shell batch per
  page load, or root and use `op 8`/`op 5`.
* **`fork()` copies the cred.** Patching a forked child's cred roots nothing —
  the cred that matters is the one the RPC thread itself uses. That is why the
  tail-scan-for-`PHYSRPC1` route is the only walk-based one worth trying.
* **The task list is damaged on this kernel, repeatedly, within seconds of boot.**
  `init.tasks.prev` dies at hop 5–17 with a non-pointer (`0x88eb08ab`,
  `0x0f0060fd`, `0x4a100031`); the app's own walk shows twenty `per/0` entries.
  Freshly allocated task_structs often read back as `0xff` fill or stale bytes,
  so a comm-based match can fail even though the address is right.
* **List-independent root that works every time** — scan for the cred pattern.
  An owner `struct cred` holds `ids = (5001,100,5001,100,5001,100,5001,100)` at
  `cred+4`: 32 bytes that do not occur by accident. Scan lowmem for it, read the
  refcount at `cred`, skip implausible values, patch. `tools/scan_cred.py`
  patched 253 creds in one pass and the next `op 7` came back `uid=0`. See
  `tools/scan_cred.py`; the parent-pointer variant (`root_parent.py`) stays in the lab.
* **Where things live:** creds and task_structs sit in phys `0x20000000`–
  `0x40000000` on this unit. Do **not** scan past `0x46000000`: two full scans
  both hung there (once followed by a TV reboot), which is why the scan is
  bounded to `0x40000000` now.
* **`ls` on this Tizen only prints the SMACK label with `-Z`.** A label check
  without `-Z` silently reads an empty string — that is how a deploy can look
  green and still produce an unlaunchable app.
* **`chsmack` works without CAP_MAC_ADMIN when the file's current label equals
  the caller's** (relabel-your-own-object). Changing *our own* label via
  `/proc/self/attr/current` is **denied** even as uid 0 — Tizen's
  > **Correction 2026-10-22 18:48:** the claim below that
> `/proc/self/attr/current` is always denied is **wrong**. A root task with the
> patched cred (uid 0 + full caps) *can* write its own label - measured twice, and
> that is what restored the payload. Treat "denied by smack_onlycap" as
> context-dependent and always retest it.

`smack_onlycap` restricts capability bypass to a privileged label. So a root'@

Repl "$lab\AGENTS.md" @'
    browser label access to another app's label (`docs/FAILED.md`, "The app lane is
    one-way from a stock TV"). One-way consequence: keep the payload installed;
    if it must be removed, plan a label source first — a SMACK relabel in kernel
    memory via the physmap is the remaining candidate.
  shell with the browser label cannot read the app's `bin/`, and you must get
  the app's label (or its channel) to work there.
* **The server must prefer a freshly queued stub** over the current one: a
  wedged stub otherwise blocks every later attempt until the server restarts.
  `lab_server/server.py` now takes a queued fresh stub in preference.
* Post-hang/dead-socket cleanup: restarting the server is the reliable reset
  after a TV power cycle (hard power-off leaves a zombie socket with no FIN).

## What is left

1. DONE (2026-10-22 15:57): the two script fixes, this write-up and a
   list-independent root tool (`tools/scan_cred.py`) are in the production repo
   `samsung_tv_root`; `AGENTS.md`, `README.md` and `docs/SCRIPT-REVIEW.md` there
   were corrected (the earlier "AUL does not start the app" claim is marked as
   wrong).
2. Re-run the **uninstall** test with the label fix in place — it should now
   restore stock *and* leave a bootable stock app (the old test could not tell
   "stock app broken" from "our payload broken").
3. Optional: second cold boot to double-confirm, and a longer soak of the
   120 s `video40` retry with the browser also running.
4. The pid-hash/IDR locator is still blocked and no longer needed: the cred
   pattern scan replaces it.
