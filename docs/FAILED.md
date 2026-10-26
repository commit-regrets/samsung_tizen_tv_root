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
- **`op 7` (RUN) is one-shot per stub** (measured). The first
  `fork+execve("/bin/sh")` works and physmap keeps working afterwards; a second
  `op 7` on the same stub times out and the stub is then deaf. Budget one shell
  batch per page load.
- **A wedged stub used to block everything.** The gateway kept its socket
  forever, so a deaf stub answered every later client with a cached hello and
  nothing else. The server now prefers a freshly queued stub; after a TV hard
  power-cycle, restart the server anyway (no FIN arrives, so the old socket
  looks alive).

## SMACK labels — the wall, and how it was actually solved

Why the label matters: the app's `bin/` is writable only by the app's **own**
label — the shipped policy grants no cross-app rules — and the app directory is
`User::Home` with `transmute=TRUE`, so a file written *while carrying the app
label* inherits it and the app can read it. The task was therefore to get that
label onto our process.

### What did not work: relabelling through kernel memory

`tools/smack_relabel.py` tried to rewrite `cred->security->smk_task` directly. The
structures were located, but the approach is **impossible on this unit**: the
`smack_known` struct lives above `0xE0000000`, in vmalloc space, where
`phys = va - 0xA0000000` does not apply — so the physmap cannot read it. 635 copies
of the label string exist in `0x20000000–0x40000000` and none of them is pointed at
by a `smack_known`.

Two hard-won facts from that attempt are worth keeping:

- our `cred->security` is at **cred+0x64** and really is a `task_smack`, provable
  by the self-referential `smk_rules` list inside it
  (`e3870f80 e3870f80 c747b848 c747b848`);
- the stub's own task is `init.tasks.prev` **immediately after a `fork()`** — no
  list walk needed, which matters because the list is damaged within seconds of
  boot.

A workaround — copy the app's label pointer out of the app's own process
(`cred->security->smk_task`) — lives in `tools/smack_relabel.py` (the old
`tools/smack_borrow.py` named here never existed in this repo), but it needs the
app process, and `tools/find_task.py` found **zero** matching tasks in two full
sweeps. One likely reason is documented below: the scans searched for
`MultiControl*`, and the app's comm is `DN_trol-Service`.

Also learned: long `readmany` scans desync the stub — a batch aborts on an unmappable
page, stray bytes follow, and every later read returns a garbage status, which looks
exactly like a clean negative. `tools/find_task.py` reconnects and resumes rather
than restarting.

### What works: relabel in userspace

From a root shell whose cred is patched to uid 0 with full capabilities:

```sh
echo -n "User::Pkg::com.samsung.tv.MultiControl-Service" > /proc/self/attr/current
cat /proc/self/attr/current      # verify it took
```

and the shell carries the app's label. `deploy.sh` then runs unchanged from that
shell: `RELABEL=ok`, `COPY=ok`, `DLL_LABEL=…::RO`, `AOT=disabled`, `BOOT_ROW=ok`.
`server/recover.sh` packages the whole procedure.

An earlier note here said `/proc/self/attr/current` is denied by `smack_onlycap`.
That was **wrong** — or at least tried from a shell without the patched cred.
Retest it before believing it. What `smack_onlycap` does restrict is capability
bypass, so a capability alone is not enough.

### Why this looked impossible for hours

- the app's process `comm` is **`DN_trol-Service`** (its exe is
  `/usr/bin/dotnet-launcher-inhouse`), **not** `MultiControl*` — every physical scan
  for the app searched for a name that never exists;
- the app is **invisible in the browser shell's PID namespace**, so `/proc` looks
  empty even while `aulctl status` reports it running with a pid;
- `aulctl reload` does **not** restart a running app — `ctl stop` + `start` does.
## How the payload was originally installed (answered)

The first swap was an **in-place overwrite**, not a copy:

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

* the deploy must carry (or be) the **app's label** — either because the channel
  process is the payload itself, or because the shell took the label in userspace
  first (`/proc/self/attr/current`, see above);
* the `::RO` files inside `bin/` are readable by the app because the app label
  matches, and the app root is `User::Home` **transmute=TRUE**, so files created
  while carrying the app label inherit it - no `chsmack` needed.

Also learned: `chsmack <path>` with **no options prints** the label
(`access="..." transmute="..."`); there is no `-p` option.

## The app lane is one-way from a stock TV — superseded

> **Superseded.** The conclusion below was right about *the browser label* and
> wrong about the *possibility of re-installing*. A root shell can take the
> app's label directly with
> `echo -n "User::Pkg::com.samsung.tv.MultiControl-Service" > /proc/self/attr/current`,
> after which `deploy.sh` writes the payload as the app's own file. The payload
> was reinstalled and verified on a cold boot (v33: 39 s). See
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

The consequence, as it looked at the time: **once the payload is removed, the
browser lane can root the TV but cannot put the payload back.** Every deploy that
worked ran from the **app's own 31337 channel**,
whose process label matches the app directory. The first install therefore has to
come from a context that already carries the app label — which is exactly what the
userspace relabel above provides. (The other routes named at the time: a write
primitive from the installer, which refuses to overwrite existing files, or a
kernel-memory relabel, which is impossible here.)

The practical rule still holds for a different reason: **do not uninstall without a
plan to get the label back**, because a plain browser-labelled root shell cannot
recreate it by itself.

## Misdiagnosis trap (cost most of a day)

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
