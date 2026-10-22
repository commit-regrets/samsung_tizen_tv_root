# Root methods — what was found

Every route evaluated on this unit, with the verdict. The two that matter are
the **V4L2 media physmap** (the novel primitive) and the **on-boot app lane**
(what makes it permanent).

## Method matrix

| # | Method | Verdict | Why |
|---|---|---|---|
| 1 | Browser RCE + **V4L2 `/dev/video40` physmap** → cred patch | **WORKS** | Arbitrary physical R/W from an unprivileged renderer; no kernel corruption needed |
| 2 | **On-boot dotnet-inhouse app** with replaced IL | **WORKS** | Stock `app_onboot` service on writable `/opt`; no signature check on launch; UEP never sees managed IL |
| 3 | Boot payload + **TCP 31337** root channel | **WORKS** | Re-roots at every boot, closes the device, serves root commands |
| 4 | sdb shell / `appinstall` injection (SVE-2025-50109) | DEAD | Shell is whitelist-only; injection never executes |
| 5 | sdbd `root:on` | DEAD | Capability 10005 not implemented by the plugin; always "disabled" |
| 6 | Mali GPU CVEs (CVE-2025-0072 / -0819, CVE-2023-6241) | OUT OF RANGE | Job-Manager Bifrost r48p0; 0072 is CSF-only, 6241 ends r25, 0819 has no PoC |
| 7 | `tztv_frc_tcon` `call_usermodehelper` slots | DEAD CODE | No caller in any shipped module; poking the node risks TCON flash |
| 8 | `/dev/tzmem` | DESIGNED SAFELY | Phys derived from real `struct page`; no physmap |
| 9 | `wasutility` | CLOSED | Root commands only get hardcoded/validated paths, never optarg |
| 10 | Package installer absolute-path write | NO EXEC CONSUMER | Writes new files only; no root-executed writable path found |
| 11 | systemd units / D-Bus `StartTransientUnit` | DENIED | systemd does not read `/opt`; D-Bus call is AccessDenied from uid 5001 |
| 12 | UEP bypass (tmpfs exec, `s_uepStatus`, LD_PRELOAD) | BLOCKED | Shipped kernel differs from GPL source; unsigned exec blocked even as root |
| 13 | `core_pattern` overwrite | UNRESOLVED | Writable, but SIGSEGV did not invoke the handler (RLIMIT_CORE/dumpable) |
| 14 | Buxton keys / developer-mode escalation | NO KEYS | Only `db/sdk/develop/{mode,ip}` exist |
| 15 | Firmware flash / kernel patch | LAST RESORT | Secure-boot and signed VDFS4 superblock unknowns |

Details on the failures are in [`FAILED.md`](FAILED.md).

## 1. The new primitive: media/V4L2 physmap

**What it is.** The codec device `/dev/video40` implements `mmap` by calling
`remap_pfn_range()` with a page frame number taken from the user's `vm_pgoff`
and **without validating that the page belongs to the device**. Any process
that can open the device can therefore map arbitrary physical memory.

**Why it is new (for this platform).**

- Earlier Samsung TV physmap work (e.g. `/dev/ntksys` on 2020 Tizen 5.5 sets)
  used a vendor debug node that exposed physical memory directly. That node is
  not present on Tizen 9.
- This primitive is a **generic Linux media/V4L2 class bug**, not a
  Samsung-specific debug interface: the authority check that should tie a
  mapping to the device's own buffers is missing.
- It requires only `gid video` — which the browser renderer already has — and
  no kernel memory corruption, no ROP, and no signed code.

**Impact.** Full physical read/write on a device whose kernel otherwise blocks
unsigned exec and module loading. That is enough to patch `cred` and obtain
`CAP_MAC_OVERRIDE`, which defeats SMACK and makes every root-owned path
writable.

**Constraints.**

- One RDWR opener per device; hold it only as long as needed.
- Each `mmap` covers one page (4 KB); a scan is many small mappings.
- Reading an invalid pfn can fault and kill the process: treat the stub as
  short-lived.
- The device is 0660 `root:video`; a process without gid 44 cannot use it.

**Why it beats the alternatives.** It gives root without touching the boot
chain, without flashing, and without depending on any of the dead sdb/UEP
routes; and because it only needs a physmap, it survives kernel symbol changes
as long as the offsets are re-measured.

## 2. Persistence: the on-boot app lane

The root primitive is RAM-only (a reboot loses it). Persistence uses a stock
service app instead of a boot hook:

- `com.samsung.tv.MultiControl-Service` is a **dotnet-inhouse** app marked
  `app_onboot` and installed on the writable `/opt` partition.
- The .NET launcher has **no signature check** on the managed assembly; it
  loads `bin/MultiControlService.dll`.
- The runtime prefers an AOT image (`bin/.native_image/<X>.ni.dll`). Renaming
  that directory forces the IL path. Original kept at
  `/opt/usr/home/owner/share/mcs_ni_orig.dll`; IL backup `mcs_orig.dll`.
- **The DLL must carry the app's SMACK label**
  (`User::Pkg::com.samsung.tv.MultiControl-Service::RO`). A file written by the
  browser keeps the browser's label and the app is then denied read on its own
  assembly — the .NET host aborts before `Main` and it looks like the app was
  never launched. `server/deploy.sh` sets the label and verifies it with
  `ls -lZ` (plain `ls` hides the label); `server/uninstall.sh` relabels the
  stock files. See `docs/BOOT-REGRESSION-SMACK.md`.
- The app-boot manager starts it at boot; its row lives in
  `/opt/dbspace/user/5001/.appsvc.db` (`boot_sequence`), with `app_onboot` in
  `/opt/dbspace/.pkgmgr_parser.db`.
- The app runs as **uid 5001, gid 44 (`video`)** — exactly the two things the
  physmap needs.
- UEP checks ELF/script files, not managed IL, so the payload is invisible to
  it.

The payload replaces the IL once — from the app's own channel, or from a root shell
that has taken the app's label — then at every boot it roots itself, writes a proof
file, closes `/dev/video40`, and listens on TCP 31337.

## 3. The root channel

Design goals: no dependency on the PC after boot, survive app restarts, be
usable from any LAN machine.

- Listens on `0.0.0.0:31337`.
- Line protocol: send one command + `\n`; output is returned, terminated by
  `__END__`.
- Commands run through `/bin/sh -c` with a 15 s timeout.
- If `/opt/usr/home/owner/share/next.dll` exists, the payload installs it over
  itself and exits so AUL restarts it with the new code (self-update).
- AUL restarts the app after a crash; measured recovery: **~12 s**, and the new
  instance is root again.

Binding `0.0.0.0` means anyone who can reach the port has root, so the payload also
supports an allowlist: if `/opt/usr/home/owner/share/rootchan.allow` exists (one IP
per line, written by `deploy.sh`), peers not listed are rejected. With no allowlist
file the channel is open to all.

## What "permanent" means here

> **Currently installed and verified on cold boots: the channel is up in ~40 s with
> no PC and no browser involvement.**
>
> Installing it does not need the kernel-memory relabel that was originally
> planned: a root shell can take the app's SMACK label directly with
> `echo -n "User::Pkg::com.samsung.tv.MultiControl-Service" > /proc/self/attr/current`,
> after which `deploy.sh` runs unchanged from that shell. `server/recover.sh`
> packages the whole procedure (relabel → deploy → restart).
>
> Two operational notes: `aulctl reload` does **not** restart a running app, so
> `deploy.sh` does a stop+start (detached, because `aulctl stop` blocks while the
> payload is running); and an OTA that replaces the app undoes all of this.

- Boot → app starts → payload roots → channel up, no browser, no PC.
- Kill the app → AUL restarts it → roots again, in ~12 s.
- Verified on two consecutive cold boots and one deliberate SIGKILL.
- After the SMACK-label fix, a cold boot gave
  `start uid=5001 → self-patch uid=0 → ROOTCHAN 31337 uid=0`. A kill/restart test
  re-roots on AUL's next relaunch — seconds in the common case, up to a couple of
  minutes early in boot. See `docs/BOOT-REGRESSION-SMACK.md`.
- **Timing, measured after v9:** cold boot → **root in ~40 s**.
  The app cannot rely on its first launch: it exits after two failed rounds
  (`self=00000000` — the task list / fresh task_structs read back stale over the
  physmap early in boot). From v9 the app therefore **exits on purpose** after a
  short attempt and lets AUL relaunch it (~1–4 s later); a fresh process re-mmaps
  `/dev/video40` and reads coherent memory. Four such fast attempts are allowed
  (counter in `/tmp/.dsh_try`, which resets at boot), then it falls back to the
  long in-process retry mode (6 rounds with backoff, then exit).
  Measured: 38 s (attempt 2) on a clean cold boot; 83 s (attempt 3) on a boot
  whose task list was badly damaged; **11 minutes** on the same kind of bad boot
  under v8, which had no fast-exit. `logs/beacons.log` shows the whole sequence
  (`attempt=N`, `fail round`, `fast-exit`, `SUCCESS-R00T`), so a slow boot is
  visible rather than mysterious.

It is not firmware-level persistence: an OTA that replaces the app, or a
factory reset, removes it. Keep auto-update off; restore `mcs_orig.dll` to
return the app to stock.
