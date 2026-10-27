# Open issues — current state, pending work, and closed history

## Current state — 2026-10-27 (v41 verified: cold boots, kill -9, uninstall/recover)

TV: **v41** (`1ab4343e…`, 33,792 B), rooted via 31337. Every beacon carries
`tok=814bce42` (from `rootchan.token`); forged and token-less beacons are refused.
`id -u` = 0, `CapEff=0x3fffffffff`.
**All hardware gates are closed (2026-10-27):** v41 cold boots at **36 s**
(attempt 1 fast-exit t=29, attempt 2 direct-parent t=36) and **49 s** after the
recover cycle (AUL launched late; one direct-patch attempt); `kill -9` recovery
**~2 s**; uninstall verified (stock IL `f61f60dd…`, AOT `6c9bdcc4…`, boot row 0,
allow removed, 31337 stayed closed after a cold boot, stock 9197 back); recovery
via `recover.sh <pc-url>` completed `DEPLOY_DONE`/`RECOVER_DONE` and the following
cold boot rooted again.
Backups: `mcs_orig.dll` (stock), `mcs_ni_orig.dll`, `payload_backup.dll` = v41.

The repo is green offline (`python tools/test_all.py`, 10/10) and
`sanitize_for_public.py --check` passes. The kernel memory boundary is now
zoneinfo-derived (`max_low_pfn 0x50400` → `high_memory` VA `0xF0400000`); the
meminfo-derived `0xE4E42000` was wrong (vendor-adjusted counters): see item 2.

**Pending / next, in order:**

1. **~~Deploy v41 / cold boot / kill -9 / uninstall + recover~~ — all done 2026-10-27.**
   Restart-rooted in ~1 s; token live; cold boots 36 s and 49 s; `kill -9` back in
   ~2 s; uninstall restored stock and stayed unrooted through a cold boot;
   `recover.sh` with the PC URL reinstalled v41 and that boot row fired on the next
   cold boot. The run also fixed two `recover.sh` bugs (rendered-guard marker grep,
   Tizen UEB unsigned-file refusal) and added `auto_root --script-args`.
2. **High-half read mechanism — boundary corrected by zoneinfo; DMA window suspect.**
   Reads at/above `0xE0000000` were unreliable (0/21 high creds, 0/81 high task
   pointers), but that line is *inside* the linear map: `/proc/zoneinfo` (2026-10-27)
   has Normal `start_pfn 0x20000`, HighMem `start_pfn 0x50400`, so `max_low_pfn =
   0x50400` and `high_memory` is **VA `0xF0400000`**. `meminfo` is vendor-adjusted
   (HighTotal 303,104 pages > HighMem present 198,656), so the earlier
   `0xE4E42000` estimate was wrong. Prime suspect now: the video40 DMA window
   (~512 MiB, matching "reads past 0x46000000 hang"), not the CPU map. One
   deliberate high-PA read and a re-read of the v38 `high-scan` verdicts against
   `0xF0400000` are still worth doing; neither blocks attempt 2.
3. **31337 is an unauthenticated LAN root shell.** The allowlist is the only
   filter on the channel. The PC side gates the shell slot to peers that announced
   themselves, answers unknown HTTP methods with 405, caps the stub queue and
   refuses cross-origin `/save`. **Both halves are now token-gated:** the `PGDB`
   handshake carries a per-run token (v40, live 2026-10-27), and the payload
   prefixes every beacon with `tok=` from the deploy-rendered `rootchan.token`
   (v41, live 2026-10-27); the server refuses unknown tokens and never admits a
   token-less beacon to the shell slot. Residual: a LAN peer on the allowlist can
   still reach 31337. Keep the set off untrusted networks; see `SECURITY.md`.
4. **Portability** — no second model/firmware has been tested. Follow
   `docs/PORTABILITY.md`; the payload now tries `video40/30/60`, but the browser
   gate (Chromium 120) and the physmap primitive are still unproven elsewhere.
   Record each unit's results there.
5. **Reference-derived follow-ups (from the wider `samsungtv` tree), in value
   order:** a per-run task tag (`PHYSRPT`+pid) plus a pid/tgid and
   `real_cred == cred` check to retire the stale-task family for good; OTA
   hardening beyond the buxton key (`/mnt/backup/OS_UPGRADE_FLAG` +
   `systemctl mask --runtime` for `swu-auto-upgrade.*`, `fw-update-service.*`,
   `fw-usb-update-service.*`, `was-background-update.*`); a portable DWARF offset
   reader with a `--check` gate. (~~`sanitize_for_public.py`-style checker~~ —
   done 2026-10-26: `tools/sanitize_for_public.py`.)
6. **Public-release hygiene** — `LICENSE` (MIT for original work), `NOTICE.md`
   (third-party browser chain is not relicensed), logs and build output ignored,
   only the payload DLL and the physrpc shellcode blob tracked as binaries. The
   baked addresses are now TEST-NET placeholders (`192.0.2.1`);
   `tools/sanitize_for_public.py --check` is green in-tree (2026-10-27) and
   `docs/REFERENCE-MATERIALS.md` points contributors at the download sources for
   firmware/GPL sources/sim tooling. **Blocking before publishing: git history
   still contains every private token (real IPs, model/firmware strings, and the
   device DUID - filter-repo with the sanitizer's token list, or publish a
   fresh/squashed history).** Also decide whether `.zcode/` (agent scaffolding,
   6 files tracked since 1b05289 despite the .gitignore rule) ships.

## History

The review notes (`docs/REVIEW-FINDINGS-2026-10-23.md` and
`docs/REVIEW-FINDINGS-DUMMY-SECOND-PASS.md`, both untracked and marked "do not
commit") **were deleted on 2026-10-24** once every item below was closed. Their
detail and line numbers live on in this file, in `CHANGELOG.md`, and in the code
comments. This file is the record: what was broken, what fixed it, and how it was
proven.

Historical state (v13, 2026-10-24): TV rooted with payload **v13** (21,504 B, md5
`176914345bcc81ca8c87de712b4a044f`), 47 tracked files, working tree clean.

Already fixed and committed with this handoff: **#9** (`patch_full` read `uid`
from `cred+40`, i.e. `cap_inheritable`; now `cred+4`, named cap offsets, proven by
`tools/sim_rpc.py`), prod `server/index.html` (it was the pre-fix copy: no service
worker unregister, static `?v=5` cache key), `payload/out1*` untracked, and the
stale doc constants (`v7` → v13, 36 → 47 files, sizes/hashes).

## Status 2026-10-24 — all PC-side items closed

Payload **v14** (23,040 B, md5 `5b798012ae35c9c567fa7a5ea91d6683`) is deployed and
verified on the TV, including a forced cold reboot.

| # | State | Evidence |
|---|---|---|
| 1 | **closed** | `Beacon()` 500 ms connect cap; boot after the change still rooted (`ROOTCHAN` +2 s after the successful attempt) |
| 2 | **closed** | fork children `close(_fd)` + `waitpid(WNOHANG)`; a boot-time attempt-1 failure followed by attempt-2 success no longer hits the 120 s open retry |
| 3 | **closed, proven on a stock state** | the stock IL/AOT were put back on disk and the backups deleted; the next deploy created them (`BACKUP_IL=ok`, `BACKUP_NI=ok`) with md5s `f61f60dd…` / `6c9bdcc4…` and recorded `mcs_orig.md5` / `mcs_ni_orig.md5` |
| 4 | **closed** | both `.ps1` pass `$TvIp`, check the exit code; `root_shell.py` also accepts `ROOT_TV` and fails on a broken stream. `uninstall.ps1 -NoWait` ran end-to-end on the TV: stock IL/AOT restored + relabelled, boot row removed (`remain=0`), `UNINSTALL_DONE`, exit 0 |
| 5 | **closed, proven on the TV twice** | `recover.sh <pc-url>` → `RECOVER=deploy.sh (rendered by server.py)` → `DEPLOY_DONE` → `RECOVER_DONE`. The 2026-10-27 run also fixed the marker-grep/rendered-guard bug and the UEB `sh /tmp/file` refusal (now fed through stdin), both gated by `test_constants` |
| 6 | **closed** | lock released before `rpc_queue.get`; `tools/test_gateway.py` asserts `RSET` in ~2 ms while a client waits |
| 7 | **closed on hardware** | silent client dropped at 30 s, second client served in 31.3 s after it |
| 8 | **closed** | label verified on the temp DLL before the rename; boot-row and AUL failures now `exit 1`. `tools/test_shell.py` now exercises the label-mismatch and bad-boot-row aborts offline (a real mismatch on the TV is not forceable without breaking it) |
| 9 | **closed** | `POST /save` body cap 1 MB → 413, proven by the gateway test |
| 10 | **closed on hardware** | stub clamps `READ`/`WRITE32`/`READMANY`/`RUN`/`FILE`; live: oversized READ and cross-page WRITE refused with `-22` while the stub kept serving, overlong op 7 refused and ended the stub. Blob rebuilt (7552 B) and re-embedded automatically |
| 12 | **closed** | allowlist fails closed; `ALLOW=` printed before `COPY=ok` on the live deploy |
| 13 | **closed** | `SaneCred` (range, alignment, usage, ids) before every cred write; payload v14 |
| 14 | **closed** | shared `iter_owner_creds` with a 31-byte carry; `sim_rpc` self-test proves the straddle case |

P2 items are fixed as well (dead `physmap` modes removed, `MapPage` munmap,
`TrySelfUpdate` PE check + rollback, `tv_rootwatch` python discovery + loop, the
`physrpc.S`/blob drift, `find_task.py` runs from a clone, doc constants).

**Nothing on that list is open any more.** The review list is fully closed, and so
is the last item that sat outside it (`AGENTS.md` §11: 31337 binding). The offline
layers are `python tools/test_all.py`, the on-TV layer is `--tv`
(`docs/TESTING.md`). The 2026-10-26 independent review's findings are a later,
separate list — see "Current state" above, `CHANGELOG.md`, and the deferred items
there.

## Second-pass review — 2026-10-24 (later)

An independent re-read of the landed fixes found four leftovers. Three were
PC-only and are fixed; the fourth is a payload change, staged.

| # | Leftover | State |
|---|---|---|
| L1 | `tv_rootwatch.root_by_tail` returned `"already"` on the first uid-0 tag — a stale task's cred pointer can land on init's (or a previously patched) cred and hide the live uid-5001 stub | **fixed**: only uid-5001 creds are written, uid-0 tags are remembered without stopping; `already` only when no uid-5001 cred exists. Cases added to `tools/sim_rpc.py` |
| L2 | `deploy.sh` continued past `BACKUP_IL=fail` / `BACKUP_NI=fail`, so a failed stock snapshot still reached `COPY=ok`/`DEPLOY_DONE` and re-opened the no-backup hole | **fixed**: both `exit 1` before anything is replaced; four new `tools/test_shell.py` checks (IL and NI failure) with a `cp` stub that fails on demand |
| L3 | `SaneCred` accepts uid 0, and the payload patched a cred whose uid is 0 *or* 5001, so a bogus `real_parent` on init's cred would still be written | **fixed in payload v15**: `PatchCred` refuses anything but uid 5001 (uid 0 = already done); deployed and boot-verified 2026-10-24 21:38 |
| L4 | `tools/_selfroot.py` still used the single-hit walk; the two `REVIEW-FINDINGS-*.md` files are still on disk | `_selfroot.py` **fixed**; the review notes were **deleted** once L1–L3 were closed (untracked, so the content lives on in this file and `CHANGELOG.md`) |

## Third pass — 2026-10-24 (evening)

Three comments on the landed work, all PC-side (the TV was in use and was not
touched):

| # | Comment | State |
|---|---|---|
| P1 | `kernel_root.py --fork` still wrote any sane cred, uid 0 included — the browser-lane twin of old M4 (the payload was gated in v15, the Python tools were not) | **fixed**: `kernel_root.patch_ours()` reads the uid and only calls `patch_full` for 5001; a uid-0 cred is reported "already uid 0 - nothing written" and never touched. Used by `root_via_fork` and the legacy `root()`; the fork scan keeps going after a uid-0 target. Two `sim_rpc.py` cases (uid-0 untouched, 5001 patched, foreign uid skipped) |
| P2 | `ListenOn` falls back to `0.0.0.0` when the specific bind fails (address not up yet), reopening the wildcard for up to 30 s | **accepted, not reverted**: only when the TV has no route at payload start; the beacon records it (`chan bind … failed`) and the 30 s re-derive moves to the real address. The normal case binds the LAN address immediately |
| P3 | Glued comment in `Program.cs` 299–302 | **fixed** (source-only; comments do not enter the IL — both versions build to the same hash). Side finding: a rebuild embeds the git SHA in `AssemblyInformationalVersion` (`1.0.0+<sha>`), so its md5 differs from the committed artifact even with identical source — take `WANT=` from the new build when deploying. **Pinned in v17** (`IncludeSourceRevisionInInformationalVersion=false`), so builds are now reproducible |

## Fourth pass — 2026-10-25 (slow boot)

A cold boot took ~3.5 min (`/proc/uptime` 227 s). Not a dead payload: attempts
1–4 fast-exited, attempt 5 long-retry `round=1` rooted via `direct-parent+2f0`.
Hypothesis 3 (pre-fork snapshot) is out — the wait loop already re-reads the
list head. The marker distinguishes the other two:

| What the marker showed | Cause |
|---|---|
| Attempt 3: `parent-patch uid=5001` ×5, `getuid()` still 5001 | ARM cache aliasing: `MapPage` kept the VA, so the cred write was visible in our mapping and not to the kernel. The ARM stub munmaps every op and does not hit this |
| Attempt 4: `pre=0 child=… self=00000000`, no `direct-parent` beacon | Latched a `PHYRFORK` whose parent cred was not uid 5001 (orphan reparented to init after `Environment.Exit`) |
| `self=00000000` on the successful round; `per/0` comms | Normal. Working path is `direct-parent`. `per/0` is the init thread name |

**v23 cold boot: latch proven, patch still attempt 2.** Attempt 1 `child=cc335640`
then `fail round 0/1` (no `direct-parent` beacon). Attempt 2 `SUCCESS` at `t=44s`.
Do not `systemctl --force reboot`. Full handoff is **Fifth pass** below.

## Fifth pass — 2026-10-25 (attempt-1 patch) — **closed**

**Closed 2026-10-25:** attempt 1 is an allocation lottery on this unit. v32
reverted the harmful 10 s wait and closed the pass with attempt 2 as the floor;
v33 added the `high-alloc` fast-exit, and the next cold boot rooted at 39 s
(attempt 1 gate, attempt 2 root). Do not reopen attempt 1 without a new read
path — more rounds/waits made it worse (v31: 132 s). The history below is kept
for the evidence and the dead ends.

**Goal as originally written:** cold-boot `SUCCESS` on **attempt 1**, not attempt
2. Hunt is no longer the blocker. Do not spend time on latch/`skip-orphan`
unless a new beacon shows `fail no new PHYRFORK` again.

The fifth pass started on **v23** (`cad2e704…`, 25,600 B); the constants and
carrier below are unchanged through v33. Cold boot = wall unplug (not remote
standby, not `systemctl --force reboot`).

### What is proven

| Boot | Attempt 1 | Attempt 2 |
|---|---|---|
| v21 | `seen=1 skip-orphan=1`, `child=0`, fast-exit | `direct-parent+2f0` → `SUCCESS` ~40 s |
| v22 | same (`pu` was not 0 / unreadable, still `child=0`) | `SUCCESS` 43 s |
| **v23** | **latches** `child=cc335640`, then **`fail round 0` / `fail round 1`**, no `direct-parent` / `self-patch` / `parent=` beacon | `child=…` then immediate `direct-parent+2f0` → `SUCCESS` **44 s** |

v23 change: any new `PHYRFORK` not in `pre` is latched; `PatchCred` still writes
uid **5001 only**. `pre` excludes leftovers. `sim_rpc.py` covers the latch.

Working SUCCESS path is always `direct-parent+2f0` (child `real_parent` → our
task → cred). `self=00000000` and tail `per/0` comms are **normal** even on the
successful round — do not chase a comm scan on attempt 1.

### Attempt-1 v23 beacons (verbatim shape)

```
t=25s attempt=1 (fast mode)
t=25s round=0 pre=0
t=28s child=cc335640 self=00000000     ← latch worked (v22 never got here)
t=33s fail round 0                     ← ~5 s of silent patch retries
t=34s round=1 pre=0
t=35s child=c5978b80 self=00000000
t=40s fail round 1
t=40s fast-exit attempt=1
t=43s start uid=5001 pid=3726          ← AUL relaunch, fresh mmap
t=43s attempt=2 (fast mode)
t=44s child=c597f300 self=00000000
t=44s direct-parent+2f0=ca2be1c0 cred=df30cf00
t=44s direct-patch uid=0
t=44s SUCCESS … ROOTCHAN bind=<tv-ip>
```

`fail round` means `getuid()` still 5001 after: skipped `self` (comm unread),
**8×** `DropPages` + direct-parent (`CredUid` never 5001, so no
`direct-parent+` beacon), then **5×** 700 ms PHYSRPT scan (comms are `per/0`,
so no `parent=` beacon). Code: `payload/Program.cs` hunt ~862, `PatchCred` /
direct-parent ~911–980, fast-exit ~1011.

### Ruled out

- Landmark not found (that was v21/v22).
- `ReopenVideo` after fork (v20, `fd=-1`). v23 still logs `reopen video40 fd=67` before the hunt.
- Need to patch uid 0 / init — `PatchCred` must stay 5001-only (v15).
- Lengthening in-process retries on the **same** mmap — v9 measured that slower than `Environment.Exit` + AUL relaunch. Fast-exit is why boot is 44 s not 3.5 min.

### Likely cause

First process after a cold boot: physmap reads of **parent / cred uid** are
stale (not 5001), so `PatchCred` refuses. Same pointers on attempt 2 (new
process, new mmap) read 5001 immediately and the write sticks (`cacheflush` +
`DropPages` in `PatchCred`, v18). Twin of the v17 "mapping uid=0, getuid 5001"
alias, but here the **read** of uid is wrong so we never write.

Missing diagnostic: direct-parent retries are silent unless uid==5001. Next
payload should beacon the uid/`pu` actually read on that path (`direct-parent
uid=` / `pu=`), then we will know 0 vs garbage vs unreadable vs 5001-that-
didn't-stick.

### How to prove a fix

Cold boot (wall unplug), browser closed. Want:

```
attempt=1
child=…
direct-parent+2f0=…     ← must appear on attempt 1
direct-patch uid=0
SUCCESS … t=<~40s
ROOTCHAN
```

Attempt 2 SUCCESS only = not fixed. `python tools/sim_rpc.py` first; it does
not model "first mmap of the boot is incoherent", so a green sim is not
attempt-1 proof.

### Do not

- `systemctl --force reboot` (deep standby; only a mains unplug wakes it).
- Serve `:80` with `python.exe` on this PC (`pysrv.exe` only).
- Close `/dev/video40` in the parent while a landmark child holds it.
- Patch a cred whose uid is not 5001.
- Repeat v20 (`ReopenVideo` after `fork`) or v22's 0/unreadable-only latch.

**Do not repeat this session's mistakes:** the `:80` server MUST run as
`pysrv.exe` — Windows firewall has inbound *Block* rules for `python.exe`, so a
`python server.py` server is invisible to the TV (no page, no beacons) while it
looks fine from the PC's own loopback. The remote power button is standby, not a
boot; only a cold boot runs the AUL hook. **Do not reboot the TV with
`systemctl --force reboot` from the payload:** on 2026-10-24 that left the set in a
deep standby that the remote could not wake and only a mains unplug cleared. Ask
for a power cycle instead.

A second footgun found the same day: `kernel_root._find_tag_near_tail()` returned
only the *first* `PHYSRPC1` task, which can be a freed one from an earlier page
load, so `root_via_fork` retried six times on a dead cred pointer
(`skip 0xe234cf00 (not a cred)`) while the live stub sat further along. It now
collects every tagged task (`_find_tags_near_tail`) and patches whichever
validates; the same fix is in `tv_rootwatch.root_by_tail`.

### Fifth pass progress — v24–v27 deployed 2026-10-25 (cold boot pending)

The code changes this pass asked for are on the TV (**v29**,
`b8923d2f7f10996d9cea72554d9333ff`, 29,184 B): the alias-correct physmap
window, the `pu=` beacon on `child=`, and the `direct-probe` diagnostics.

What the probes found (mid-session relaunches reproduce the staleness family,
so no cold boot was needed to iterate):

| Observation | Meaning |
|---|---|
| v24 (8 KiB slots): `cred=7fffcad4` / `cred=00000000` while `cuid=5001` | the cred **pointer** word read stale from the parent task page — task pages, not just cred pages |
| v25 (16 KiB slots): `parent` == `self`, `pu=5001` on some attempts | pointer reads coherent through the window; alignment past 8 KiB matters |
| v25: `uid=1769238121` (ASCII `"inti"`) at a cred whose pointer looked right | the attempt-4 anomaly — explained below, fixed in v27 |
| v26 + v27: counter-cleared relaunches root at **attempt=1** (`pu=5001` → `direct-parent+2f0` → `SUCCESS`, or via `self`) | the v23 "attempt 1 never reads 5001" signature is gone on clean first processes |

#### The attempt-4 anomaly, explained (v27)

Symptom: one v25 relaunch attempt read ASCII `"inti"` at `cred+4` (where 5001
belongs) while the *same process* read the task pages coherently
(`parent == self`, comm matched). Next attempt, fresh process: coherent, SUCCESS.

Reason (best supported hypothesis, derived offline from the beacons): with v25's
16 KiB slots, `VA = win + slot·0x4000 + (page & 0x3FFF)` fixes PA bits 12–13
but leaves **PA bit 14 to slot parity** — `VA[14] = win[14] XOR slot&1` — so
alias status per page was a 50/50 decided by slot allocation order. Both
observed window bases (`a8280000`, `a8480000`) are ≡ 0 mod 32 KiB, so
window-base geometry cannot explain attempt-4-vs-attempt-5, but slot parity
can. The failing cred page (PA `0x2033d000`, bit 14 = 1) needed an odd slot and
got an even one; the task page (PA `0x1e0f1000`, bit 14 = 0) matched. Hence the
**alias period is 32 KiB** (L1 way size), not 16 KiB, and v25's hole sat
exactly at bit 14. v27 sets SlotStride = 0x8000 (VA ≡ PA mod 32 KiB, bits
12–14 guaranteed), and two counter-cleared relaunches on v27 rooted at
attempt 1 with no probe lines.

Remaining discriminator if a stale read ever shows up again (cold boot or
relaunch): the `direct-probe` line now carries `map=` (window VA the cred page
is mapped at) and `pva=` (the plain mmap's VA). Compare `map`/`pva` bits 12+
against the cred PA's bits: a mismatch means the staleness is still VA
geometry (raise the stride); `uid` == `plain` == garbage with every bit matched
means the kernel's dirty line is unreachable from userspace (writeback-latency
story — the fix would be churn/eviction, not mapping geometry), and `head=`
says whether the cred pointer itself is stale (page not cred-shaped).

Remaining: the **wall-unplug cold boot**. Want on attempt 1: `child=…` →
`direct-parent+2f0=…` → `direct-patch uid=0` → `SUCCESS` → `ROOTCHAN` at
t≈25–35 s. Attempt-2 SUCCESS only = not fixed; a `direct-probe` line is the
next lead, not a regression (attempt 2 still roots as before).

#### Cold boot on v27 (2026-10-25, wall unplug) — decoded, still attempt 2

Attempt 1 ran its full fast budget (t=17s→37s), fast-exited; attempt 2 rooted
at t=41s via `self`-patch. The v27 probe fired and pinned the cold-boot-specific
stale read:

```
t=22s child=cee0cac0 self=00000000 pu=unread
t=22s direct-probe pr=0 po=2f0 parent=e3891cc0 cred=00000000 uid=unread
      plain=unread head=- map=- pva=- ccred=d86f4780 cuid=5001
```

Reading it: the child's `real_parent` (child+0x2F0) read coherently —
`parent=e3891cc0`, stable across all 8 retries and both rounds. The **cred
pointer field in our own task (parent+0x3F8) read `00000000`** — impossible for
a live task (`start uid=5001` proves `getuid()` works), so that line is stale.
Our own task's comm read stale too (`self=00000000`, same page). The child task
page and the child's cred page read coherently (`cuid=5001`). `head=`/`plain=`
did not fire — they only run when the cred pointer is a kptr (probe gap).

Two conclusions:

1. **Pure VIPT aliasing is ruled out for this failure.** The failing page
   (PA `0x23891000`) has PA bits 13–15 = 0, so with 32 KiB slots its mapping is
   alias-correct regardless of slot parity — and still read stale for 20 s.
2. Leading suspect: the physmap mapping's memory type does not snoop hot dirty
   L1 lines. A running task's page (scheduler/tick writes) stays continuously
   dirty in the running core's L1, so physmap reads of it return stale RAM
   indefinitely; the landmark child **sleeps**, so its page writes back within
   milliseconds and reads coherently — exactly the observed child-coherent /
   parent-stale asymmetry, and it also fits `getuid()` working (the kernel
   reads its own cached lines).

Next steps, in order:

- ~~Probe gap fix (diagnostic)~~ — **done in v28**, and the next relaunch
  answered it: `uid == plain` garbage through two different VA geometries
  (`map=a82a7000` vs `pva=b48d6000`) — **the RAM content itself reads stale;
  VIPT aliasing is fully ruled out.** The staleness is content visibility with
  a ~15-20 s convergence window; v9's "fresh process fixes it" was the delay,
  not the restart.
- ~~Likely fix (fallback path)~~ — **done in v28**: `CredScanNear` scans
  outward from the child's cred page (±1 MiB, lower addresses first), patches
  sane uid-5001 creds except the child's own, stops at the first `getuid()==0`.
  First live run: `cred-scan miss patched=4` — mechanically correct, but our
  cred page was among the stale ones. Collateral (4 foreign app creds rooted
  until reboot) is real and capped; **v30 makes the 8-cred cap process-wide**
  and only spends it in rounds after a wait.
- **v29: wait out the window in-process.** Fast-mode rounds are now
  `{0, 0, 5000, 5000}` and the fast PHYSRPT scan is trimmed to 2 tries. If the
  content converges in-process, attempt 1 roots at the same wall clock attempt
  2 used to; if not, fast-exit and AUL relaunch follow unchanged. The next
  cold boot decides: attempt-1 `SUCCESS` closes the fifth pass; an attempt-1
  that still fails after the waits proves the first-process effect is
  structural (not time), the fast-exit design is final, and the probe lines
  name it.
- **v30: review fixes (deployed 2026-10-25; cold boot run, attempt 1 still fails).**
  The failed fixed-map fallback now restores the slot hole with
  `MAP_FIXED_NOREPLACE` (and switches the window off if it cannot), `ReleasePage`
  checks its re-protect, the scan's 8-cred budget is process-wide and only spent
  in post-wait rounds, and an offset-0 pattern hit no longer closes the page. The
  Python twin now models the early break and the budget, with self-tests. The
  deploy relaunch's attempt 1 failed (stale parent and child cred pages;
  `cred-scan skip`, no collateral) and attempt 2 rooted. **The cold boot then also
  failed attempt 1** — see below; the fifth-pass acceptance is **not met**.

#### Cold boot on v30 (2026-10-25, wall unplug) — attempt 1 still fails

`attempt=1` started at t=22 and attempt 2 rooted at t=51. The chain:

```
t=24s child=… cuid=5001  direct-probe pr=0 … cred=00000000 uid=unread
      pplain=0 phead=000000000000000000000000000000000000000000000000 pmap=a8291000
t=28s round=1 … same (cred=00000000, cuid=5001)
t=38s cred-scan miss patched=1 total=1      ← gate opened, scan ran, ours stale
t=44s round=3 … ccred=<new child> cuid=unread
t=45s cred-scan skip anchor=… cuid=unread   ← child cred page now stale too
t=47s fast-exit attempt=1
t=49s start uid=5001 pid=4138              ← AUL relaunch
t=51s SUCCESS … self-patch uid=0            ← attempt 2, fresh process
```

Reading it: our own task's cred-pointer line read zeros in every round, while the
child's task/cred pages were coherent in rounds 0–2 (`cuid=5001`). The v30 gate
opened in round 2 and the scan ran at t=38, but patched only 1 and missed ours —
our cred page was still stale. Round 3 forked a new child whose cred page was
stale too (`cuid=unread`), so the gate skipped it. The window ended between t=45
and t=51; attempt 2 was coherent on arrival. The scan gate/budget did its job
(one foreign cred patched, no repeat).

Conclusion: four rounds did not outlast this boot's window, and the v31 10 s last
wait made the next cold boot **worse**: attempt 1 failed (round 3's hunt saw no new
`PHYRFORK` at all), attempts 2/3 ran 30+ s and failed, and **attempt 4 rooted at
t=132 s**. The full-log analysis found the failure is **address-dependent, not
time-based**:

| Observation | Count |
|---|---|
| coherent child creds (`cuid=5001`) with `ccred < 0xE0000000` | 78 / 78 |
| child creds `>= 0xE0000000` reading 0 / junk / `0xFF` | 21 / 21 |
| `direct-parent+` successes with a cred `< 0xE0000000` | 15 / 15 |
| `self-patch uid=0` successes with a cred `< 0xE0000000` | 19 / 19 |
| task pointers (`child=`/`self=`) ever `>= 0xE0000000` | 0 / 81 |

A 1–2 s old process read coherently when its allocation was low (v30 attempt 2),
and a 1–2 s old process failed when its cred was high (v31 attempt 2) — so "fresh
process" is not the variable, the **allocation address** is. Attempt 1 is an
allocation lottery: every observed cold-boot first process landed high, and no
in-process retry can change where its task/cred live. Only a fresh process re-rolls.

**v32 reverts the 10 s wait** (`{0,0,5000,5000}`) and fixes the direct-probe
`pmap=` lookup to use the page that holds the cred field (`V2P(parent)+O_CRED`), so
the `pmap=plain` lines are not mistaken for a window fallback (there was no
`physmap fixed map failed` beacon). The fifth pass is **closed as "attempt 2 is the
floor"**: cold-boot acceptance is attempt 2 `self-patch uid=0` / `SUCCESS` at
≤ ~55 s; attempt 1 is a bonus. v32 is deployed (`a4ccba98…`) and its deploy
relaunch rooted at attempt 1 in ~1 s. Its cold boot (2026-10-25 18:25) confirmed
the closure: attempt 1 failed as predicted (`parent=e37fb980` high, `cred=ffffffff`;
round 3's child cred high → `cred-scan skip`), fast-exit t=55, **attempt 2 rooted at
t=59** (`self=d9356780`, `cred=c5b78080`). No 132 s regression; 59 s is in the
v30-profile class.

- **v33: high-alloc fast-exit (optional latency; deployed 2026-10-25).** The
  remaining cost was attempt 1 spending ~55 s on a high allocation it cannot read.
  v33 sets `highAlloc` from the direct-parent probe and, in fast mode only, beacons
  `high-alloc … fast-exit` and breaks to the existing fast-exit instead of running
  the waits/scan. It requires no low cred/real (`sawLow`), so a low-but-write-failed
  cred keeps the normal retry/scan path, and it is fast-mode only so long mode
  cannot loop exits. Deploy relaunch rooted attempt 1 in ~1 s. The cold boot
  (2026-10-25 18:35) validated it: attempt 1 found `parent=e3400b80` high, beaconed
  `high-alloc … fast-exit` at t=32, AUL relaunched at t=36, **attempt 2 rooted at
  t=38–39 — 39 s vs 59 s on v32**.

The attempt-1 marker to look for: `attempt=1` → (optionally `retry in 5s`)
→ `child=… pu=5001` → `direct-parent+2f0=…` → `direct-patch uid=0` →
`SUCCESS` → `ROOTCHAN`. Attempt-2 `SUCCESS` is now the accepted floor; an attempt-1
`SUCCESS` is a bonus, and a `direct-probe`/`cred-scan` line is still useful evidence.

## Environment — read before touching the TV

- **Work in this repo.** The `samsungtv` tree is reference material (vendored
  clones, firmware extract, the DWARF/kernel build). Nothing under it is needed to
  fix the items below, and nothing there should be edited as "the toolkit".
- **TV:** `<tv-ip>`, rooted, payload **v34** (`5c780eea…`), channel on
  `31337` (`python tools/root_shell.py "id" <tv-ip>`). PC: `<pc-ip>`.
- **Port 80 is the firewall's fault line.** The Windows firewall has inbound
  *Block* rules for `python.exe` and *Allow* rules for `pysrv.exe` (path
  `...\pythoncore-3.14-64\pysrv.exe`, plus a "TV lab HTTP (pysrv)" rule). Serve
  `server.py` with `pysrv.exe` or the TV cannot fetch the page and beacons never
  arrive. `root.ps1`'s `Find-Python` already prefers `pysrv.exe`; a manual
  `python server.py` does not.
- **Payload builds:** any dotnet SDK ≥ 8 builds the `net6.0` project; the
  `NETSDK1138` "out of support" warning is expected. A payload change means: rebuild,
  copy the new DLL over `server/payload.dll` (the deploy gate is rendered from it), deploy over the channel, reboot, and
  check the beacon chain — `AGENTS.md` §7/§9.
- **Do not launch a second server** while the task's one owns `:80`; the TV would
  fetch whichever answered.

## P0 (historical, closed) — a promise the docs make that the code does not keep

| # | Issue | Why it matters | Fix sketch | How to verify |
|---|---|---|---|---|
| 1 | **`Beacon()` blocks with no connect timeout** (F15) | The headline claim is "root at boot with no PC". Every beacon is a synchronous `TcpClient.Connect`; a stale host on another subnet costs TCP SYN retries inside the ~40 s budget. The 38–47 s measurements were all taken with the PC reachable. | Short connect timeout (~500 ms) or fire-and-forget; keep the local marker file as the durable record. | Boot with the server **down**; measure first beacon → `ROOTCHAN`. Should stay ≈ the same. |
| 2 | **Fork children hold `/dev/video40` for 120 s** (F8, M1) | Each failed fast round forks a child that sleeps 120 s holding the inherited device fd, so the parent's `close()` frees nothing. The next AUL launch then sits in the 120 s `open()` retry — this is a plausible cause of the slow boots v11 tried to fix. | In the child: `close(_fd)` before the sleep (raw syscall only — `AGENTS.md` §9), and close before `Environment.Exit`. Reap children (`SIGCHLD`→`SIG_IGN` or `waitpid`). Payload rebuild: bump version, update `WANT=`/size, deploy, reboot. | Cold boot whose task list is unreadable; beacons must not show `fail open video40 after 120s`, and boot-to-root should tighten. |
| 3 | **Nothing creates `mcs_orig.dll` / `mcs_ni_orig.dll`** (F5) | `uninstall.sh` hard-fails without them. On this TV they exist because they were made by hand; a first-time user can root and then never cleanly uninstall. | In `deploy.sh`, before replacing anything, snapshot the current IL and `.native_image/*.ni.dll` to `share/mcs_orig.dll` / `mcs_ni_orig.dll` **if absent**, md5-gated the way `uninstall.sh` checks them. | On a stock TV: deploy, then compare both backups' md5 against the known stock values; then uninstall. |
| 4 | **`root_shell.py` address requirement breaks both `.ps1` callers** (F1) | `root_shell.py` exits 2 without an address (`$TV_IP` or argv[2]); `uninstall.ps1` and `root.ps1` call it with only the command, and `root.ps1` never checks `$LASTEXITCODE`, so it prints "Permanent root is up" even though the check never ran. The uninstall path cannot run at all. | Pass `$TvIp` as the second argument in both scripts and check the exit code. Audit other call sites and docs using the bare form. | `python tools/root_shell.py id` → exit 2 (confirms); after the fix, `root.ps1 -DryRun` and a real uninstall run. |
| 5 | **`recover.sh` fetches the un-rewritten `deploy.sh`** (F3) | `deploy.sh` still contains `H="http://HOST_IP"`; only `root.ps1` rewrites it (into `deploy_local.sh`). So `recover.sh` ends in `CURL_FAIL` and still prints `RECOVER_DONE`. It also points at `tools/chan.py`, which does not exist. | Fetch `deploy_local.sh` when present, else rewrite `H=` inside `recover.sh`; abort unless the output contains `DEPLOY_DONE`; fix the hint to `root_shell.py`. | Run `recover.sh` from a root shell on the current TV: expect `COPY=ok` … `DEPLOY_DONE`. |

## P1 (historical, closed) — robustness; no user-visible promise broken

| # | Issue | Fix sketch |
|---|---|---|
| 6 | **Gateway holds `rpc_lock` while waiting** (F2) — `rpc_queue.get(1800)` runs inside the lock, so whenever a client is waiting (the common flow: the tool connects before the page is opened) `RSET`, forwarding and a second client all block. This is why `reset_stub()` can time out. | Claim the client slot under the lock, release it, wait on the queue, re-acquire to pair. Add the integration test below. |
| 7 | **31337 serves one client at a time with blocking reads** (F7) — one silent connection (port scan, half-open socket) makes the channel deaf until the app restarts. Same class as the v12 pipe wedge, one layer up. | Read timeout + maximum command length in `Serve()`. |
| 8 | **Fatal conditions report success** (F4) — `DLL_LABEL_MISMATCH`, `BOOT_ROW_WARN`, `AUL_RELOAD=fail`, and uninstall's `LABEL_WARN` are warnings, then `DEPLOY_DONE` / `UNINSTALL_DONE`. `auto_root.py` only requires `DEPLOY_DONE,COPY=ok`. | Make them `exit 1`. First check a live `DLL_LABEL=` line: if Tizen's `ls -lZ` ever prints extra fields, a correct deploy would start failing. |
| 9 | **`POST /save` Content-Length uncapped** (M2) — headers are capped, the body is not, so any LAN client can grow `logs/tv/`. | Cap the body (e.g. 1 MB) and reject the rest. |
| 10 | **No size enforcement between PC tools and the stub** (F11, M3) — `run_root`/`auto_root`/`write_root` send arbitrary lengths into fixed stub buffers (`cmdbuf 512`, `pathbuf 256`, `databuf 4096`); the stub never clamps `offset+len` to the mapped page. | Enforce 509 B commands, 255 B paths, 4096 B chunks client-side; clamp in the stub too. |
| 12 | **31337 allowlist fails open** (F12) — missing file ⇒ allow all, and `deploy.sh` writes the allow file *after* the DLL, so an interrupted deploy leaves an open root shell. | Write the allow file before the DLL; fail closed. Note the trade-off for hand-copied payloads in the docs. |
| 13 | **`PatchCred` has no sanity check** (M4) — it accepts any kernel-looking pointer whose cred uid is 0 or 5001, so a bogus `real_parent` could patch a foreign cred (even `init`). Python's `_sane_cred` is stricter. | Mirror `_sane_cred` in the payload (usage 1..0x10000, ids plausible) before writing. |
| 14 | **Cred scan misses a page-straddling pattern** (M5) — `scan_cred.py` and `tv_rootwatch` search each 4 K page with no overlap. Proven by the `sim_rpc.py` self-test: a 16/16 split is invisible per page, visible with 31 bytes of overlap. | Carry `PAT[:-1]` as overlap between pages. Extend the sim test to cover the fix. |

## P2 (historical, closed) — hygiene, latent paths, or cosmetic

- **`physmap.py` dead modes** (F6): `full_root` calls `load_image_head()` (no uImage ships), then undefined `find_tasks_offset`/`walk_tasks`, and gates creds to `< 0xD0000000` while claiming success. Not on the production path (`kernel_root.py --fork`). Delete or repair.
- **`TrySelfUpdate()`** (F13): any `share/next.dll` over 1 KB replaces the payload with no hash check and no rollback. **Removed in v34** rather than hardened — it was unused and an unauthenticated payload-replacement path.
- **`MapPage`** (F14): `Pages.Clear()` leaks mappings without `munmap`; the `mmap2` fallback's `r < 0` is too strict for a high-half mapping (a successful map is a negative `int32`). **Do not** touch `mmap64`'s `== -1` check — that half of the finding was wrong.
- **`tv_rootwatch.py`** (F16): hardcodes the author's `pysrv.exe`; loop mode returns after the first successful shell (only `--no-shell` loops).
- **Embedded shellcode ≠ `tools/physrpc.S`** (F10): the shipped blob's device path decodes as `/dev/video30`, the source says `/dev/video40`. It works (same driver family), but a rebuild + re-embed would silently switch nodes. Align them, or rebuild and re-verify, and add a build check comparing blob against assembly.
- **`root.ps1` may claim persistence it did not observe** (low): `deploy.sh` restarts the app in the background, so 31337 usually opens *before* any reboot. Wait for down-then-up, or say so plainly.
- **`uninstall.ps1`**: undeclared `$NoServer` (its `-NoServer` switch cannot bind); `Stop-ToolkitServer` lacks the process-name check that `root.ps1` has; it waits only 20 s for 31337 to reappear while payload startup measures ~40 s — a false "uninstall verified" is possible.
- **`server.py` shell bookkeeping**: `tv_sock` is never cleared on disconnect, the global `output` grows unbounded, and `control_client`'s saved offset can exceed `len(output)` after a clear (swallowing that client's output).
- **Doc/naming hygiene**: `root_shell.py`'s docstring says `chan.py` (it is the `chan.py` client renamed); `_selfroot.py` and `taskwalk.py` are diagnostics with sharp edges — label them as such.
- **Delete the two `REVIEW-FINDINGS-*.md` files** once the list above is closed.

## Tests to add (they would have caught these)

1. **Fake-RPC unit tests** — `tools/sim_rpc.py` is now in the repo (`python tools/sim_rpc.py` self-test). Extend it: page-straddle scan (M5) and the `PatchCred` sanity analogue.
2. **Gateway integration test** — start `server.py` on a scratch `HTTP_PORT`, attach a waiting client on 9998, assert `RSET` answers within ~1 s, then queue a fake `PGDB` stub and assert pairing/forwarding. Catches #6.
3. **Shell dry tests** — run `deploy.sh`/`uninstall.sh` under `sh` with stubbed `curl`/`sqlite3`/`chsmack`/`aulctl` on `PATH`; assert non-zero exit on label/boot-row mismatch (#8) and that the stock backups get created (#3).
4. **PowerShell** — `root.ps1 -DryRun` and `uninstall.ps1 -DryRun` after #4, plus a stubbed `root_shell.py` invocation test.

## Suggested order

1. #4 (one line ×2) — restores the uninstall path.
2. #6 — gateway lock restructure.
3. #8 + #3 — fail loud, and create the backups.
4. #5 — recover path.
5. #2 + #1 + #7 — payload: close the device in children, beacon timeout, channel read timeout. Payload rebuild, `WANT=`/size, deploy, reboot, verify per `AGENTS.md` §7.
6. #14, #13, #10, #12 — sanity, sizes, allowlist ordering.
7. #9, then P2.

Payload work is the only part that needs a TV round-trip and a reboot; do the PC-side
items first so a reboot validates several changes at once.


## Deferred from the 2026-10-26 second review

These were reviewed, deliberately **not** done in the v39.2 batch, and are listed
so the next session does not rediscover them:

- ~~**Per-run token in the 12-byte hello**, covering `TV_PEERS` admission (not
  just the stub)~~ — **done 2026-10-26 (PGDB half)**: the page generates a
  per-load token, announces it (`POST /pair`) and patches it into the stub
  (`TOK1` placeholder, `tools/physrpc.S`), which sends it as the 4 bytes after
  `PGDB` **before the device open** (a slow open no longer looks like a silent
  raw peer). The server refuses an unannounced/mismatched token and only then
  admits the peer to `TV_PEERS`; the gateway reconstitutes the 12-byte
  client-facing hello, so no RPC client changed. Covered by
  `tools/test_gateway.py` (announce/mismatch/match). **Still open:** a forged
  `DSHROOT` beacon still joins `TV_PEERS` — closing that (and `beacons.log`
  forgery) needs the payload to know a token, i.e. a `rootchan.token` rendered
  by `deploy.sh` and read by `Beacon()` (payload v41); see `SECURITY.md`.
- **A `tools/` constants module.** The offsets/limits are duplicated across
  `Program.cs`, `sim_rpc.py`, `kernel_root.py`, `physmap.py`, `physrpc.S`, the
  page and `deploy.sh`; `test_constants.py` catches drift, but a shared Python
  module (generated or imported) would remove it. Deferred because it touches
  every tool for no behavioural gain on this unit.
- **Split `server.py` into client/gateway/http modules**, a class-based gateway,
  a threaded accept loop (a slow HTTP client still costs the single accept
  thread up to 10 s), and a split of `sim_rpc.py` / `payload/Program.cs` into
  partials. Offline tests exist, but the refactors are riskier than their value
  until the hardware lane is available.
- **Research-tree ports:** ~~the public-release sanitizer pipeline~~ (**done
  2026-10-26**: `tools/sanitize_for_public.py`; in-tree tokens replaced with
  TEST-NET placeholders 2026-10-27, `--check` green), ~~a DWARF type reader~~
  (**done 2026-10-27**: `tools/dwarf_offsets.py` with a `--check` fingerprint
  gate - the sim vmlinux matches every TV-measured offset, `tasks` included),
  ~~the layout-shift-proof list walk~~ (**done 2026-10-27**:
  `tools/listwalk.py`, back-link-validated candidates plus a comm-tag walk
  with no struct-offset assumption; offline-tested in `tools/test_listwalk.py`),
  plus `taskwalk.py` orphan detection, a QEMU/softmmu physmap harness, and a
  C `cred_scan` utility. The remaining three are the right next investment
  for porting, not for this firmware.
- **High-PA read test** and the `high_memory`/`max_low_pfn` read: the two
  falsifiable checks in `AGENTS.md` §11.
- **Encoding hardening beyond stdout:** the three CLIs now use
  `errors="replace"`, but a few tool file reads/writes still rely on the locale;
  pin `encoding="utf-8"` when touching them (Python 3.15 will default to UTF-8,
  this runtime does not).
- **`beacons.log` forgery:** rotation bounds the disk-fill half, but a LAN peer
  can still append a forged `DSHROOT` line. The PGDB pairing token (above) does
  not cover beacons; the payload-side `rootchan.token` (v41 sketch there) is
  the fix for this.
