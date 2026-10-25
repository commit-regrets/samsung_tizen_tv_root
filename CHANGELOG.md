# Changelog

All notable changes to this toolkit, newest first. Dates are day-level and times
are deliberately omitted — the *why* of a change belongs here, the *how* belongs
in `docs/`.

**Maintenance rule:** every change to the scripts, payload, server or docs gets an
entry here, under `Unreleased` if it is not part of a dated batch. A change with no
entry is an incomplete change. `AGENTS.md` repeats this rule for agents.

---

## 2026-10-25

### Payload v35 — high-alloc gate must not be vetoed by junk on a high parent page

A high parent task page is exactly the half video40 cannot read, so its
`cred`/`real_cred` words are junk. The v33 gate still fed those words to
`sawLow`: a junk value in `0xC0000000..0xDFFFFFFF` looked like a readable low
cred and suppressed `highAlloc && !sawLow`, keeping the 5 s waits and the scan
instead of re-rolling. The existing boots happened not to hit it
(`b51a4594`, `0`, `ffffffff`), which is why the gate looked reliable.

- Ignore `cred` and `real_cred` for `sawLow` when the **parent** pointer is at or
  above `0xE0000000`; a low parent with a readable low cred still keeps `sawLow`.
- The gate beacon now logs the raw word read, not only high kptrs: a high parent
  with `cred=b51a4594` logs `cred=b51a4594` instead of `cred=00000000`.
- `tools/sim_rpc.py` gains `high_alloc_gate()` and tests the junk-word case, the
  zero/non-kptr log case, a genuine low-cred suppression, high-cred/high-real
  firing, and long mode never fast-exiting. All sim tests pass.
- Build `e33d6f6a7e415e033db1e26a2a99ecb2`, 29,184 B, reproducible (two builds).
  Deployed; on-TV md5 verified. Cold boot (2026-10-25 21:54) confirmed the gate:
  attempt 1 parent `e2df7300` high, raw cred `b09aa3b5` logged, gate at t=26 and
  fast-exit; attempt 2 rooted at t=37. A v35 boot now exercises the raw-word
  beacon and the high-parent path.

### auto_root — retry root on a fresh stub (root.ps1 reliability)

The 2026-10-25 stock→root cycle showed the one-command path failing when the
browser stub died during root: `root.ps1` ran `auto_root` once and exited. A
manual fresh page + `kernel_root.py --fork` worked, so the failure was stub
lifetime, not addressing.

- `tools/auto_root.py` now treats a failed root as a dead single-use stub: it
  prints a **RELOAD the page** request, sends `RSET` to the gateway, waits for a
  fresh stub, and retries up to `--root-retries` total attempts (default 3). It
  also gives the renderer 1 s to settle after pairing.
- `root.ps1` passes `--root-retries 3`, says so in the prompt, and its dry run
  shows the option.
- New `tools/test_auto_root.py` fakes the RPC/kernel layers and asserts the loop
  resets and retries; `tools/test_all.py` runs it. All offline layers pass.
- A full stock cycle with the retry loop is the remaining acceptance; the loop
  is the automation of the manual recovery that already worked.

### Payload v34 — remove the unauthenticated `next.dll` self-update; drop remote/OTA scope

- Removed `TrySelfUpdate()`, `LooksLikeAssembly()` and the startup call. Any
  process that could write `share/next.dll` could install a PE that the boot app
  runs, with only PE-header sanity and no hash/signature. It was unused and
  untested, so it is gone rather than hardened. Payload 29,184 B,
  `5c780eea5ca951fb05dee5da37fa6186`, reproducible (two builds).
- Removed `docs/REMOTE.md` and `tools/tv_ws_launch.py` (investigation only;
  the TV's remote WebSocket refused it), the `websocket-client` dependency, and
  the remote/`next.dll`/OTA items from `AGENTS.md` and `docs/OPEN-ISSUES.md`.
  OTA remains a warning — keep auto-update off; measuring it risks the root.
- Deployed; on-TV md5 verified. Cold boot (2026-10-25 19:40): attempt 1 high
  (`parent=e3a08b80`), `high-alloc` gate at t=25, AUL relaunched, **attempt 2
  rooted at t=34** — 34 s, better than v33's 39 s. This removes unused code
  only; the boot path is unchanged.
- **Full stock→root cycle (2026-10-25, 19:45–20:00).** `uninstall.ps1` restored
  the stock IL/AOT and removed the boot row; after a cold boot, 31337 stayed
  closed. `root.ps1` then generated `deploy_local.sh` with the auto-detected PC
  address and started, but its auto-root failed twice on the browser stub
  (`probe 0x40008000 timed out`; then `no PHYSRPC1 task found`). A manual
  `python tools/kernel_root.py --fork` on a freshly reloaded page rooted, and
  `run_root.py "curl …/deploy_local.sh | sh"` deployed v34 (`HOST_FILE=…`,
  `COPY=ok`, `DEPLOY_DONE`). The final cold boot needed **attempt 3 at 68 s**
  (attempt 1 high gate, attempt 2 hunt `seen=0`, attempt 3 root). So the
  no-static-IP address path works end to end, but `root.ps1`'s automated
  browser-root step is not reliable from a fresh stock boot yet; the manual
  fallback is the proven path.
- Manual procedure fix: `AGENTS.md` and `docs/EXPLOIT.md` now deploy
  `deploy_local.sh` (written by `root.ps1`), not the committed `deploy.sh` —
  the latter carries the placeholder `H=` and hangs if served as-is.

### Payload v33 — high-address fast-exit (optional boot-latency lever)

v32 reverted the harmful 10 s wait and closed the fifth pass at attempt 2 (59 s cold
boot). The remaining cost is that attempt 1 can spend ~55 s on a high allocation
that video40 cannot read. v33 adds one **fast-mode-only** gate: after the
direct-parent probe, if the parent task or its cred is at/above `0xE0000000` and no
low cred/real was ever seen, beacon `high-alloc parent=… cred=… fast-exit` and break
to the existing fast-exit instead of running the waits/scan. A fresh AUL process is
the only allocation re-roll, so a high-allocation boot should fall sharply; a low
allocation is unchanged (the deploy relaunch rooted attempt 1 in ~1 s). `sawLow`
keeps a low-but-write-failed cred on the normal retry/scan path, and the gate is
fast-mode only (attempts 1–4) so long mode cannot loop early exits.

Build: `63dc2652259cec5f0886b2dae143b837`, 30,208 B, reproducible (two clean
builds). Deployed 2026-10-25 (`COPY=ok`, `DEPLOY_DONE`; on-TV md5 verified).

Cold boot on v33 (2026-10-25 18:35, wall unplug) validated the gate: attempt 1's
round 0 hunt failed (`seen=0`), round 1 found the child with `parent=e3400b80`
(high) and a low-but-not-kptr garbage cred (`cred=b51a4594`, `pplain` the same;
`sawLow` stays false because Kptr(cred) is false), and the payload beacons
`high-alloc parent=e3400b80 cred=00000000 fast-exit` at t=32. AUL relaunched at
t=36; attempt 2 rooted at t=38–39. **Boot-to-root 39 s vs 59 s on v32** — the gate
saved ~20 s. The remaining 39 s is app start + the failed round-0 hunt + the AUL
relaunch gap, not the waits.

### Public-release preparation (docs only)

- Deleted the untracked `docs/REVIEW-BRIEF-2026-10-25.md` working note; its
  conclusions are in `docs/OPEN-ISSUES.md`, `CHANGELOG.md` and the payload
  comments. `.gitignore` no longer carries the “do not publish” marker.
- Added `LICENSE` (MIT for the original work; third-party browser-chain files
  excluded) and `NOTICE.md`'s license-scope note, plus `SECURITY.md` covering the
  unauthenticated 31337 backdoor, scope, reporting and legal use.
- `README.md`: a short “Porting to another Tizen 9 TV” checklist, a stronger
  safety/backdoor/license section, and the new docs in the index (the test-unit
  status paragraph was removed — the facts table and `docs/OPEN-ISSUES.md` carry
  what matters). `docs/PORTABILITY.md`: the v31 high-half read limit, its
  evidence, and a file-by-file port checklist. `docs/EXPLOIT.md`: the
  read-reliability limit next to the address-space table. `docs/USAGE.md`: the
  committed `deploy.sh` `H=` is a placeholder and must be rewritten by `root.ps1`.
- Removed private LAN addresses from docs, changelog entries, examples and code
  comments. `server/deploy.sh` now ships `H=http://192.0.2.1` (TEST-NET-1) as a
  placeholder; `root.ps1` still rewrites it into the ignored `deploy_local.sh`.
  The payload's compiled `Host` remains a fallback only; changing it would
  require a new payload version for no functional gain.
- `docs/OPEN-ISSUES.md` now opens with the current state and a short pending
  list (high-half mechanism, portability, unauthenticated channel, public
  hygiene, optional features) and marks the review/pass sections as history.
  `AGENTS.md` §11 carries the same pending list.
- Removed the stale “21.5 KB” `.gitignore` comment and the dangling review-note
  ignore marker.
- `AGENTS.md` no longer carries a “committed: ~N files / ~N KB” inventory; that
  was agent bookkeeping and is noise in a public handoff. `.gitignore` is the
  source of truth.
- `AGENTS.md` has a short **Caveats for a fresh clone** section: the
  `deploy.sh` placeholder vs `deploy_local.sh`, the compiled address fallbacks
  (`payload/Program.cs`, physrpc/page), the unauthenticated 31337 channel, the
  attempt-1 allocation lottery, the v34 removals, and the third-party license
  boundary.

### Payload v32 — attempt-1 root cause: high-half reads are unreliable; revert the 10 s wait

The v31 cold boot (wall unplug) was worse than v30: attempt 1 failed (round 3's
hunt saw no new `PHYRFORK` at all), attempts 2 and 3 ran 30+ s each and failed, and
attempt 4 rooted at **t=132 s**. A full-log analysis (every beacon, not just the two
cold boots) found the failure is **address-dependent, not time-dependent**:

- Every coherent task/cred read in the log is **below 0xE0000000**.
- 78/78 child creds that read `5001` were below it; 21/21 at/above it read
  0 / junk / `0xFF`, never 5001.
- 15/15 `direct-parent+` successes and 19/19 `self-patch uid=0` successes used a
  cred **below 0xE0000000**; 0/81 recorded task pointers were high.
- The control: v30 attempt 2 was 1-2 s old and read coherently at low addresses;
  v31 attempt 2 was also 1-2 s old and failed with a high cred. So "fresh
  process" is not the variable — the allocation address is.

Attempt 1 is therefore an **allocation lottery**: every observed cold-boot first
process landed high, and in-process retries, `DropPages` and the scan cannot change
where its task/cred live. Only a fresh process re-rolls the allocation. The v31
10 s wait delayed that re-roll and cost 80 s of boot time.

v32 reverts the fast rounds to `{0,0,5000,5000}` (v30 profile) and fixes the
`direct-probe` `pmap=` field to look up the page that actually holds the cred field
(`V2P(parent)+O_CRED`) instead of the task base page — the `pmap=plain` lines in the
v31 boot were that diagnostic artifact, not a window fallback (there was no
`physmap fixed map failed` beacon). No high-address fast-exit is added; it is a
valid latency follow-up, not the acceptance.

**The fifth pass closes as "attempt 2 is the floor":** cold-boot acceptance is
attempt 2 `self-patch uid=0` / `SUCCESS` / `ROOTCHAN` at ≤ ~55 s. Attempt-1
`SUCCESS` would be a bonus, not a goal.

Cold boot on v32 (2026-10-25 18:25, wall unplug): **attempt 1 failed exactly as
predicted** — `parent=e37fb980` high, `cred=ffffffff` junk, round 3's child cred
went high too (`cuid=4294967165`), so the scan skipped; fast-exit at t=55.
**Attempt 2 rooted at t=59** (`self=d9356780`, `cred=c5b78080`, both low) and the
channel came up; on-TV md5 `a4ccba98…`. The 132 s v31 regression is gone; 59 s is
within the v30-profile class (v30 measured 51 s). Attempt 1 remains a bonus.

Build: `a4ccba98cf81ef92b11cff38f33bd203`, 30,208 B, reproducible (two clean
builds). Deployed 2026-10-25 (`COPY=ok`, `RESTART=kill 5536`, `DEPLOY_DONE`; on-TV
md5 verified); the deploy relaunch rooted at attempt 1 in ~1 s.

### Payload v31 — attempt-1 tuning: last wait 5 s → 10 s

The v30 cold boot (wall unplug) still failed attempt 1. The parent task page read
stale in every round (`cred=00000000`, `pplain=0`) while the child's cred page was
coherent in rounds 0–2 (`cuid=5001`): round 2's scan ran at t=38 but missed ours
(`cred-scan miss patched=1 total=1`), and round 3's child cred page was stale too
(`cuid=unread` → `cred-scan skip`). Fast-exit at t=47; attempt 2 self-patched at
t=51. So this boot's window ended between t=45 and t=51, after v30's last round.

v31 changes one constant: the fast-mode rounds are `{0,0,5000,10000}`. Round 3
now starts at ~t=49, exactly where attempt 2 was already reading coherent memory;
round 2 keeps its 5 s wait so the scan still samples the middle of the window. The
scan gate/budget, the window fixes and the fast-exit fallback are untouched.

Build: `cb9c19c0de7dc0608357ceeb16cb4609`, 30,208 B, reproducible (two clean
builds). Deployed 2026-10-25 (`COPY=ok`, `RESTART=kill 4138`, `DEPLOY_DONE`; on-TV
md5 verified), and the deploy relaunch rooted at attempt 1 in ~1 s. The next wall
unplug decides the fifth pass: attempt-1 `SUCCESS` closes it; attempt 2 makes the
fast-exit design final.

### Payload v30 — review fixes: window-hole restore, process-wide scan budget, sim fidelity

An independent review of the v24–v29 work found one latent window-fallback hole and two
places where the Python twin did not model the C# it is supposed to lock. v30 fixes
those, plus the smaller items a second review pass turned up:

- **A failed `MAP_FIXED` is a hole, not a fallback (`MapPage` / `RestoreWindowHole`).**
  Linux 5.4's `mmap_region()` does `do_munmap()` before `call_mmap()`, so when
  `/dev/video40` refuses a fixed mapping the slot has already been unmapped. The old
  code fell back to the plain mmap and left the 4 KiB gap in the reservation;
  `_slotNext` did not advance, so the next page with the same in-slot offset
  `MAP_FIXED`ed over whatever had taken the gap (only eight in-slot offsets exist, and
  `DropPages()` resets the slot index). v30 restores the hole with
  `MAP_FIXED_NOREPLACE` — `EEXIST` instead of clobbering if a runtime thread won the
  race — beacons once, and turns the window off if the restore fails. `ReleasePage`
  now checks its `PROT_NONE` re-protect and does the same; the old code ignored the
  return and left the same class of hole.
- **The scan's 8-cred cap is process-wide, and early rounds no longer spend it.**
  `MaxPatched` was per call, so v29's four fast rounds could patch up to 32 foreign
  creds (six long rounds: 48) while the docs said 8. `_scanPatched` now accumulates
  across the process. The scan also runs only in rounds that follow a wait: the v28
  evidence has an in-window scan patching 4 neighbours and missing ours, which would
  have spent half the budget before the post-window round that can see it. The beacon
  now carries `total=`.
- **A page-offset-0 pattern hit no longer closes the page.** `while (idx >= 4)`
  aborted the whole page when the first hit belonged to a cred starting in the previous
  page; a later cred on the same page was never seen. The pre-page hit is still
  refused, but the search continues. The scan's 0x60000000 stop is deliberately
  unchanged: the 0x46000000 hang is the video30 browser stub, and the v28 probe read
  phys 0x60000000 through the video40 payload successfully.
- **Comment/version corrections:** the sim docstring said 8 KiB and "8 in-process
  retries"; `AGENTS.md` §9 and trap 15 still told the reader to skip a live foreign uid
  (the v23 latch deliberately does not); the window header still said "16 KiB slots
  since v25", and the attempt comment still described the pre-v29 "exit immediately".
- **Python twin:** `direct_parent_patch` models the v28 early break (the replica now
  emits the two pr-0 probes the C# emits, not four through pr 7); `cred_scan_near`
  models the process-wide budget, the direct-map range and the offset-0 hit, with a
  shared `budget` list for the cross-call cap; the no-kptr probe line carries
  `pplain=`/`phead=`. New self-tests lock all three (10 foreign creds stop at 8, a
  second scan with the same budget is a no-op, a later cred behind an offset-0 hit is
  still patched).

Build: `1e9b37dfa3c347128999ba5b13a7e049`, 30,208 B, reproducible (two clean builds
matched). Deployed 2026-10-25 (`COPY=ok`, `RESTART=kill 10310`, `DEPLOY_DONE`; on-TV
md5 verified). The deploy relaunch's attempt 1 failed after all four rounds with the
content stale through both the parent task page and the child's cred page — the scan
gate correctly skipped (`cred-scan skip`, no collateral, budget unspent), it
fast-exited, and attempt 2 rooted in ~1 s.

**Cold boot on v30 (2026-10-25, wall unplug): attempt 1 still failed.** Attempt 1
(t=22–47) read the parent task page stale in every round (`cred=00000000`,
`pplain=0`) while the child's cred page was coherent in rounds 0–2 (`cuid=5001`).
Round 2's scan ran at t=38 but missed ours (`cred-scan miss patched=1 total=1`); by
round 3 the child's cred page had gone stale too (`cuid=unread` → `cred-scan skip`).
It fast-exited at t=47 and **attempt 2 rooted at t=51** via `self`-patch. The
fifth-pass acceptance is therefore **not met**: this boot's window ended between t=45
and t=51, i.e. after v30's last round. The scan gate/budget did its job (one foreign
cred patched, no repeat). Next knob: a longer last wait (e.g. `{0,0,5000,10000}`)
puts round 3 at ~t=50, inside the observed convergence; otherwise the fast-exit design
is final and the fifth pass closes as "attempt 2 is the floor".

### Payload v28→v29 — cred-scan fallback, discriminator closed, wait-out-the-window rounds

v28 (cred-content scan near the child's cred + probe gap fix) was answered by
the very next mid-session relaunch, and the answer closed the fifth-pass
discriminator:

- `direct-probe … uid=251683069 plain=251683069 map=a82a7000 pva=b48d6000` —
  the same garbage through two completely different VA geometries: the page's
  **RAM content itself reads stale**. Not VIPT aliasing. The staleness is
  content visibility with a ~15-20 s convergence window.
- `cred-scan miss patched=4` — the scan works (found and patched four sane
  uid-5001 creds near the child's) but our cred page was among the stale ones.
  The documented collateral happened once; `MaxPatched = 8` now bounds it.
- Attempt 3, started ~14 s later: everything coherent, instant SUCCESS. v9's
  "a fresh process fixes it" was really "the *next* attempt, seconds later,
  reads fine" — the restart was incidental, the delay was not.

v29 therefore keeps attempt 1 alive across the convergence window instead of
fast-exiting past it: fast-mode rounds are now `{0, 0, 5000, 5000}` (the
`retry in 5s` beacons mark the waits), the fast-mode PHYSRPT scan is trimmed to
2 tries (it never fired on a stale attempt 1 — comms are stale on exactly those
attempts), and the scan patch cap bounds collateral. If the window converges
in-process, attempt 1 roots at the same wall clock attempt 2 used to; if not,
the fast-exit and AUL relaunch still follow unchanged.

On the TV: v28 (`ce10f6dd…`) and v29 (`b8923d2f…`, 29,184 B) both deployed and
verified; v29's deploy relaunch rooted at attempt=1 in ~1 s (`pu=5001` →
`direct-parent+2f0` → `direct-patch uid=0`). **The next wall-unplug cold boot
decides the fifth pass**: attempt-1 `SUCCESS` closes it; an attempt-1 that
still fails after the 5 s waits proves the first-process effect is structural
(not time) and the fast-exit design is final — with the probe lines naming it.

### Cold boot on v27 — decoded: cred-pointer line stale, aliasing ruled out

First wall-unplug cold boot on v27: attempt 1 ran its full fast budget
(t=17s→37s) and fast-exited; attempt 2 rooted at t=41s via `self`-patch. The
`direct-probe` line fired for the first time on a cold boot and pinned the
failure: the child's `real_parent` read coherently (`parent=e3891cc0`, stable),
but the **cred pointer in our own task read `00000000`** for all 8 retries and
both rounds — impossible for a live task — and our own comm read stale too
(`self=00000000`), while the child task page and the child's cred
(`cuid=5001`) read coherently. `head=`/`plain=` did not fire (probe gap: they
require a kptr cred). The failing page (PA `0x23891000`, bits 13–15 = 0) is
alias-correct under 32 KiB slots regardless of slot parity, so **pure VIPT
aliasing is ruled out** for the cold-boot case; leading suspect is non-snooping
reads of hot dirty L1 lines (running task's page continuously re-dirtied;
sleeping child's page writes back instantly). Decode, conclusions and the two
next steps (probe-gap fix; cred-content scan near the child's cred as the
likely fix, with its trade-off) are in `docs/OPEN-ISSUES.md`. Attempts remain
strictly sequential by design: attempt 2 starts only after attempt 1's process
exits.

### Payload v27 — 32 KiB slots; the v25 attempt-4 "inti" anomaly explained

v25's relaunch showed one attempt reading pre-alloc garbage (ASCII `"inti"`)
at a cred page whose pointer read fine, while the very same process read the
task pages coherently. Re-deriving the slot math from the beacons explains it:
with 16 KiB slots, `VA = win + slot·0x4000 + (page & 0x3FFF)` fixes PA bits
12–13 but leaves **PA bit 14 to slot parity** (`VA[14] = win[14] XOR slot&1`),
and both observed window bases (`a8280000`/`a8480000`) are ≡ 0 mod 32 KiB — so
geometry per page was identical across processes and cannot explain the
difference, while slot-allocation order can. The failing cred page (PA
`0x2033d000`) has bit 14 = 1 and needs an odd slot; the task page (bit 14 = 0)
matched by luck. Conclusion: the **alias period is 32 KiB** (L1 way size), not
16 KiB, and v25 left a 50/50 hole exactly at bit 14.

v27 therefore moves SlotStride to **0x8000** (2048 slots, same 64 MiB
PROT_NONE window) so VA ≡ PA mod 32 KiB, covering every way size up to
32 KiB. The direct-probe line gains `map=` (the window VA the cred page is
currently mapped at) and `pva=` (the VA the plain mmap picked) so any residual
stale read can be checked against the PA bits offline, bit by bit.

On the TV: deployed (`COPY=ok`, md5 `98874484…` on disk verified) and two
counter-cleared `kill -9` relaunches both rooted at **attempt=1** — one via
`self` (`pu=5001`, ~1 s) and one via `direct-parent+2f0` (`pu=5001`, first
retry). No `direct-probe` lines fired. **Cold-boot attempt-1 proof still
pending a wall unplug**; the expected chain is `child=… pu=5001` →
`direct-parent+2f0=…` → `direct-patch uid=0` → `SUCCESS` → `ROOTCHAN` at
t≈25–35 s. If a `direct-probe` line appears instead, `uid=` vs `plain=` and
`map=`/`pva=` vs the cred PA bits decide between VA geometry (still aliased)
and unreachable kernel dirty lines.

v27 = 28,160 B, md5 `98874484572ecdd5b1fb99457bf45907`.

### Payload v24→v26 — physmap window + direct-probe diagnostics (deployed, cold boot pending)

Fifth pass (`docs/OPEN-ISSUES.md`): cold-boot attempt 1 found the landmark but
never read the parent cred uid as 5001, so `PatchCred` never ran and the boot
needed attempt 2 (~44 s). The live marker plus new probes pinned the mechanism:
the first process reads **stale bytes** through the physmap for pages the kernel
keeps touching (a running task's struct, the app's own cred) while fork-fresh
pages (the child's comm, its cred) read coherently — the kernel's dirty cache
lines for hot pages never write back, and a physmap mapping that does not share
the kernel's VIPT cache set (L1 way size, alias period 16 KiB here) fetches
stale RAM. `DropPages` cannot fix the read direction (remapping never touches
the kernel's line); only a fresh mmap layout — what AUL's relaunch provides —
or an alias-correct mapping can.

- **v24** — every physmap page is now mapped from a reserved `PROT_NONE` window
  at **VA ≡ PA (mod SlotStride)** (`MapPage`/`ReserveWindow`/`ReleasePage`), so
  our cache line is the kernel's line and both directions are coherent; slots
  are re-protected instead of munmapped (a hole could be grabbed by another
  mmap and later clobbered by a `MAP_FIXED`); plain-mmap fallback stays. Also:
  the `child=` beacon now carries `pu=` and the direct-parent retries beacon
  `direct-probe` lines (uid read, parent/cred pointers) when the patch gate
  stays closed — the diagnostic the fifth pass asked for.
- **v25** — v24's 8 KiB alignment still showed per-line staleness on a
  mid-session relaunch (comm coherent, `real_parent`/cred pointer stale), i.e.
  the alias period is 16 KiB (64 KiB 4-way L1). SlotStride 0x2000 → **0x4000**,
  plus one-time `physmap window at …` beacons. Relaunch evidence: pointer reads
  became coherent (`parent` == `self`, `pu=5001`), but one attempt still read
  garbage at the cred **content** (ASCII `"inti"` at `cred+4`).
- **v26** — probe enriched: `plain=` (same cred uid through a plain mmap,
  different VA geometry) and `head=` (first 18 bytes at the cred) to split a
  stale cred *pointer* from stale cred *content* on the next failure.

**Result on the TV:** v26 (`f6d7e33a…`, 27,648 B) deployed over 31337
(`COPY=ok`, `RESTART=kill`, relaunch verified, md5 on TV matches). A
counter-cleared `kill -9` relaunch then rooted at **attempt=1 in ~1 s**
(`pu=5001` → `direct-parent+2f0` → `direct-patch uid=0` → `SUCCESS`) — the path
v23 never achieved on a first process. **Cold-boot attempt-1 proof is still
pending a wall unplug**; until then a stale-cred observation on a cold boot
would be named by the `direct-probe … plain=/head=` fields.

### sim_rpc: ReadStaleRPC + direct_parent_patch twin

`tools/sim_rpc.py` now models the attempt-1 failure (`ReadStaleRPC`: kernel
writes land in a dirty view the physmap read path cannot see until
`publish()` — DropPages-independent) and twins the payload's direct-parent
block (`direct_parent_patch`, incl. the v24 gate semantics: a uid-0 read
refuses, unlike `patch_ours`'s "already done"). Self-test cases: the full
attempt-1 replica (hunt finds the child, gate stays closed, nothing written,
probe names the stale pages while the fork-fresh child cred reads 5001),
`publish()` rooting on the first retry, and the probe separating foreign /
unreadable-cred-page / stale-0. `plain=`/`head=` mirror the v26 beacon format.

### Attempt-1 patch handoff

`docs/OPEN-ISSUES.md` fifth pass is the next-agent brief: v23 hunt latch is
proven, `SUCCESS` is still attempt 2 because the first process never reads
parent cred uid as 5001 (no `direct-parent` beacon). Suggested first code
change is a diagnostic uid/`pu` beacon on that path, not another latch tweak.

### Payload v23 — cold boot (latch proven, patch still attempt 2)

Cold boot: `t=25s attempt=1`, round 0 `child=cc335640` (no skip-orphan drop), then
`fail round 0` / `fail round 1` with no `direct-parent` beacon — cred uid never
read as 5001 on that first process. Fast-exit. Attempt 2 at `t=43s` latched
immediately, `direct-parent+2f0` → `SUCCESS` at `t=44s`, `ROOTCHAN`
bind=<tv-ip>, md5 `cad2e704…`, `uid=0`. Hunt latch is what v22 missed.
Attempt-1 SUCCESS still depends on a fresh mmap (the fast-exit path).

### Payload v23 — latch every new PHYRFORK (deployed, cold boot pending)

v22 cold boot (2026-10-25) still missed attempt 1: `t=32s fail no new PHYRFORK
seen=1 skip-orphan=1`, then fast-exit, attempt 2 rooted at `t=43s`. The landmark
was visible; parent cred uid was neither 5001, 0, nor unreadable, so v22 left
`child=0`. `pre` already excludes leftovers from the last round, so v23 latches
any new `PHYRFORK`; `PatchCred` is unchanged (uid 5001 only). Fail beacons now
include `pu=`. `sim_rpc` hunt/latch cases match.

v23 = 25,600 B, md5 `cad2e7042c5f4c6e1411c719c6f2fe24`. Deployed over 31337:
`COPY=ok`, `RESTART=kill 3274`, AUL relaunch `SUCCESS` pid=7294 at uptime 235 s.

### Payload v22 — cold boot (attempt 2, latch missed)

Cold boot after v22 deploy: `t=17s start`, attempt 1 round 0 `seen=0`, round 1
`seen=1 skip-orphan=1` then fast-exit; attempt 2 `direct-patch uid=0` at `t=43s`,
`ROOTCHAN` bind=<tv-ip>, md5 `17b8bcdb…`, `uid=0`. Same shape as v21 —
the 0/unreadable latch was too narrow.

### sim_rpc: hunt walk, cache alias, exclusive video40

`tools/sim_rpc.py` now twins more of the payload than the latch helper:
`hunt_new_phyrfork` walks a planted `tasks.prev` list (pre-set exclusion,
last-match, foreign uid skipped), `AliasedMemRPC` models MapPage vs kernel RAM
(v17 write-visible-in-mapping / getuid still 5001, and the v22 DropPages
re-read), `Video40` is the one-RDWR-opener rule that made v20's post-fork
reopen return -1, plus LPAE pointers above `0xE0000000`, an unreadable cred
page, a `2F4`/`2F0` mismatch, `iter_owner_creds` carry-reset on a hole, and
`write32` refusing a page-straddling store. Still `python tools/sim_rpc.py`,
no TV.

### Payload v22 — deployed (cold boot not yet proven)

Deployed over 31337 from v21: `SIZE=25088`, `MD5=17b8bcdb…`, `COPY=ok`,
`DLL_LABEL=…::RO`, `BOOT_ROW_COUNT=1`, `RESTART=kill 3226`, `DEPLOY_DONE`.
AUL relaunch at kernel uptime 34232 s loaded the new IL (`reopen video40 fd=67`,
`SUCCESS` pid=11150, `ROOTCHAN` bind=<tv-ip>). Attempt 1 of that
relaunch was `seen=0` (unreadable comms), round 1 rooted via `direct-parent`.
That is not a cold boot — the attempt-1 `skip-orphan=1` latch is still unproven.

### Payload v22 — latch stale uid-0 PHYRFORK

v21 cold boot attempt 1 saw the landmark (`seen=1 skip-orphan=1`) and discarded
it because `ChildParentIsOurs` required uid 5001. A parent cred of 0 in the
physmap is stale zeros, not init. v22 latches 5001, 0, and unreadable; skips
only a live foreign uid. `PatchCred` is unchanged (uid 5001 only). Direct-parent
re-reads up to 8 times. `tools/sim_rpc.py` has the Python twin
(`child_parent_uid` / `latch_new_phyrfork`) and would have failed the v21 rule.

v22 = 25,088 B, md5 `17b8bcdb3889ed48bd9cd0086a77f8bf`.

### Payload v21 — do not close video40 while a child holds it

v20 reopened `/dev/video40` **after** `fork()`. The landmark child still had the
inherited fd (one RDWR opener), so `open()` returned -1, `_fd` stayed -1, and
every hunt was skipped (`fail reopen video40`). 31337 never came back. v21
reopens once after `TaskOffsets`, before any `fork()`, and retries the open for
5 s. The post-fork `seen=` / `skip-orphan=` beacons stay.

v21 = 25,088 B, md5 `a87f91ee282ff6c9770513f4e42d2fcd`. Recovered via the
browser stub (`root_via_fork` + `deploy_local.sh`): `COPY=ok`,
`RESTART=kill 7992 …`, channel back in 15 s. Live: `uid=0`, md5 match,
`reopen video40 fd=67` before the hunt, then `direct-patch uid=0`.

Cold boot: channel at kernel **t=40 s** (same as v19). Attempt 1 reopened
`fd=67`, round 0 `seen=0`, round 1 `seen=1 skip-orphan=1` (ChildParentIsOurs
rejected our own landmark — parent cred not uid 5001 in the physmap yet),
fast-exit. Attempt 2 round 0 `direct-patch uid=0`. Pre-fork reopen is not
what made attempt 2 work.

### Payload v20 — reopen `/dev/video40` after fork

v19's write-side cacheflush is real (`self-patch uid=0` on the cold boot). The
remaining miss was the **first open** of the boot: attempt 1 walked `per/0` for
3 s, never saw a new `PHYRFORK`, fast-exited; attempt 2 (new process, new open)
rooted in 1 s. `DropPages()` unmaps pages; it does not replace the V4L2 file
description. v20 closes and reopens `/dev/video40` after the landmark `fork()`
so the hunt uses a fresh open without `Environment.Exit`. Fail beacon now
reports `seen=` / `skip-orphan=` so a miss is not silent. Fast-exit stays as
fallback.

v20 = 25,088 B, md5 `9f5d209438a688f56bbd0b0c8a5310ec`.

### Payload v19 + deploy restart

The v18 deploy copied the new DLL and printed `DEPLOY_DONE`, but `aulctl stop`
never returned (it blocks while the payload is the running app), so 31337 stayed
on v17 until a manual `kill -9`. Landmark children from a successful root were
also left sleeping 120 s; a later `kill -9` reparented them to init and the
warm reload spent fast attempts 1–3 on them.

- `deploy.sh` / `deploy_local.sh`: after `DEPLOY_DONE` is printed, a detached
  job `kill -9`s every process whose cmdline contains `MultiControlService.dll`
  (gated on `/dev/video40` so a PC dry-run does not walk the host `/proc`), then
  `aulctl start`. Sleeps 2 s first so the channel can send `DEPLOY_DONE`.
- Payload v19 (24,576 B, md5 `a1de129f26cf86d2e2137e9caead3194`): `KillChildren()`
  also runs after a successful root, before `RootChannel()` / self-update exit.
  Fail-round and fast-exit kills are unchanged.

Deployed over 31337: `COPY=ok`, `RESTART=kill 6637`, `DEPLOY_DONE`. AUL
respawned as pid 7022 on attempt 1 round 0 (`direct-patch uid=0`, ~1 s). Live:
`uid=0`, md5 `a1de129f…`. The `/proc/[0-9]*` glob also matched a non-pid
(`/proc/4kbtin`); the loop now skips names with a non-digit.

Cold boot (mains): channel at kernel **t=40 s**. Attempt 1 fast-exited (`fail no
new PHYRFORK` ×2); attempt 2 round 0 **`self-patch uid=0`** (the v17 failure
mode was the same patch with `getuid()` still 5001). `uid=0`, full caps, md5
match, `ROOTCHAN … bind=<tv-ip>`.

### Payload v18 — deployed (slow-boot diagnosis)

The 3.5 min cold boot was not "the list is unreadable". `share/root_boot.txt`
shows two distinct failures, then the designed long fallback:

- Attempt 3 found `self`/`parent` and called `PatchCred` five times (`parent-patch
  uid=5001`). The physmap readback saw zeros; `getuid()` stayed 5001. The ARM
  stub never hits this because it munmaps after every op; `MapPage` kept the
  aliased VA, so the write lived in our D-cache while the kernel still had uid
  5001.
- Attempt 4 `pre=0 child=c7804500 self=00000000` with no `direct-parent` beacon:
  it latched a `PHYRFORK` whose `real_parent` cred was not uid 5001 (orphan
  reparented to init after the previous `Environment.Exit`). Round 1 then
  `fail no new PHYRFORK` in the 3 s fast window.
- Attempt 5 (long) round 1 succeeded the usual way: `direct-parent+2f0` → uid 0.
  `self=00000000` is normal; `per/0` comms are the init thread names, not a
  failure. Snapshot race is not the cause — the wait loop already re-reads the
  list head each pass.

v18 (24,576 B, md5 `bff712ec10f048f8f520cdcf5c9dd285`). Changes, all fail-closed:

- `Beacon()` prefixes `t=<uptime>s` from `/proc/uptime` (PC beacons and the
  local marker), so the next slow boot shows where the minutes went.
- `Write32` `cacheflush`es the slot; `ReadPhys` flushes before copy; `PatchCred`
  `DropPages()` after a successful write so the kernel's next access of that PA
  is a miss. `DropPages()` also runs before the pre-scan, after `fork()`, and
  each wait-loop pass.
- A new `PHYRFORK` is accepted only when `real_parent`/`parent` cred uid is 5001
  (`ChildParentIsOurs`). The uid-5001 `PatchCred` gate is unchanged.
- Landmark children are `SIGKILL`ed on a failed round and before fast-exit, so
  `Environment.Exit` does not leave init-reparented orphans for the next AUL
  launch.

Fast timeouts and the 4-then-long attempt counter are unchanged.

Deployed over 31337 (`COPY=ok`, `DLL_LABEL=…::RO`, `BOOT_ROW_COUNT=1`,
`DEPLOY_DONE`). `aulctl stop` did not take the running v17 down (channel stayed
up — the known hang), so the new IL was loaded with `kill -9` of pid 4289; AUL
respawned in 37 s. Live: `uid=0`, full caps, md5 `bff712ec…`, beacons prefixed
`t=453s`, and **`self-patch uid=0`** (the v17 failure mode was `parent-patch
uid=5001` with `getuid()` still 5001). This was a warm AUL restart, not a cold
boot — leftover v17 `PHYRFORK` landmarks are why it used fast attempt 4.
Cold-boot proof is still a mains unplug. Do not `systemctl --force reboot`.

### Payload v17 — reproducible artifacts

- The v16 source build and the committed `server/payload.dll` could never agree
  after a commit: the SDK embeds the git SHA in `AssemblyInformationalVersion`
  (`1.0.0+<sha>`), so the same code built to a different md5 at every commit, and
  the MVID/PE timestamp followed it. `payload/BootPayload.csproj` now pins
  `IncludeSourceRevisionInInformationalVersion=false`. Two clean builds of the
  same source now produce the same bytes (verified), and comments never entered
  the IL anyway.
- The glued `SaneCred` comment is fixed in this build (it was source-only before,
  because a rebuild without a deploy would have desynced the artifact).
- **v17 = 23,552 B, `36d7c09f0f733cf5099b2fa591aebe5e`** (41 bytes smaller than
  v16 purely from dropping the SHA string from the metadata).
- Deployed over 31337 (label verified, `COPY=ok`, `BOOT_ROW_COUNT=1`, `DEPLOY_DONE`)
  and loaded with the documented `kill -9` path: AUL respawned it in ~11 s, beacon
  `ROOTCHAN 31337 uid=0 bind=<tv-ip>`, `uid=0`, full caps, md5 match,
  `/proc/net/tcp` shows the single-address LISTEN.
- **Cold boot (mains) on the slow path:** the first four fast attempts failed and
  the in-process fallback rooted on `round=1`, so the channel came up ~3.5 min
  after power-on (`/proc/uptime` 227 s at verification). This is the designed
  fallback when task memory is unreadable at boot, not a v17 regression (v17 is
  metadata-only vs the 33 s v16 boot); `share/root_boot.txt` is the record when
  the PC server is down. `AGENTS.md` §1 now says a slow boot means "read the
  marker", not "the payload is dead".
- `deploy.sh` `WANT=`/`SIZE_WANT=`, `AGENTS.md` §1/§5/§7/§9, `README.md` updated.

---

## 2026-10-24

Worked through `docs/OPEN-ISSUES.md` (triaged from the 2026-10-23 code review).
PC-side items were verified offline; the payload change is **built and staged, not
yet deployed** (the TV's channel went down before the deploy — see the end of this
entry).

### Added

- `tools/test_gateway.py` — integration test for the port-80 RPC gateway: starts
  `server.py` on scratch ports, proves `RSET` answers while a client is still
  waiting for a stub, that the waiting client survives it and receives the 12-byte
  hello from the next fake stub, that bytes flow both ways, that a second client
  gets `BUSY`, and that an oversized `POST /save` gets 413. It found a real bug on
  its first run (see *Fixed*).
- `tools/kernel_root.iter_owner_creds()` — the owner-cred content scan as one
  page-straddle-safe generator, now used by `scan_cred.py` and
  `tv_rootwatch.root_by_cred_scan` instead of two copies of a per-page
  `data.find()` that could never see a 32-byte pattern split across pages.
- `tools/build_physrpc.py --check-embedded` — compares `physrpc.S` with the
  `SHELLCODE` the page actually runs (byte-identical with keystone; literals-only
  fallback without it). It exists because the two had drifted.
- `tools/smack_relabel.py`: `CRED_SECURITY` and `sane_smack_blob()`, so
  `tools/find_task.py` no longer imports the reference tree's `smack_borrow`.

### Changed

- **Payload v14** (23,040 B, md5 `5b798012ae35c9c567fa7a5ea91d6683`):
  - `Beacon()` caps the connect at 500 ms. Every beacon was a blocking
    `TcpClient.Connect`; a stale `rootchan.host` could burn the ~40 s boot budget
    in SYN retries, contradicting "root at boot with no PC".
  - fork children close `/dev/video40` (`syscall(6, _fd, …)`) before sleeping, and
    the fast-exit path closes it before `Environment.Exit`. Previously each failed
    round left a child holding the single RDWR opener for 120 s, so the next AUL
    launch sat in the `open()` retry (a slow-boot cause that looked like a failed
    round). Children are also reaped with `waitpid(pid, WNOHANG)` — exact pids, so
    .NET's own `Process.Start` children are never stolen.
  - `Serve()` sets 30 s read/write timeouts, caps a command line at 4 KB and
    pending input at 8 KB. The channel serves one client at a time, so one silent
    or half-open connection used to own 31337 until the app restarted.
  - `PatchCred()` validates the cred first (`SaneCred`: physical range, aligned,
    `usage <= 0x10000`, plausible ids) — the analogue of Python's `_sane_cred`. A
    bogus `real_parent` that looked like a kernel pointer could patch a foreign
    cred (init's included).
  - The 31337 allowlist fails closed: a missing/unreadable `rootchan.allow` denies
    instead of allowing everyone. `deploy.sh` now writes that file before the DLL,
    so an interrupted deploy cannot leave an open root channel. A hand-copied
    payload needs the file too (`AGENTS.md` §1).
  - `TrySelfUpdate()` requires an MZ/PE image and keeps the previous DLL as
    `MultiControlService.dll.prev`; any `share/next.dll` over 1 KB used to replace
    the payload with no check and no rollback.
  - `MapPage()` `munmap`s when it evicts the cache (it used to `Pages.Clear()` and
    leak every mapping), and the `mmap2` fallback treats only `-errno` values
    (`-4095..-1`) as failures — a successful mapping in the top half of the
    address space is a negative int32. The `mmap64` `== -1` check was left alone
    (that half of the review finding was wrong).
- `server/server.py`:
  - The RPC gateway claims the client slot under `rpc_lock`, then **releases the
    lock before `rpc_queue.get(1800)`**. Holding it across the wait froze `RSET`,
    the TV forwarder and every later client for as long as no page was open —
    which is the normal flow, since `auto_root.py` connects first.
  - `CTRL_PORT`/`RPC_PORT` can be overridden from the environment (needed by the
    new test), `POST /save` bodies are capped at 1 MB (413 beyond), and the shell
    bookkeeping no longer leaks: `tv_sock` is cleared when the shell closes, the
    output buffer is trimmed to 1 MB with an absolute position so a client cannot
    lose output after a clear, and `rpc_tv_reader` uses the same trim.
  - The `RSET` peek timeout is 0.5 s and is now always cleared afterwards.
- `server/deploy.sh`: fail loud and snapshot the stock app.
  - `DLL_LABEL_MISMATCH`, `BOOT_ROW_WARN` and `AUL_RELOAD=fail` now `exit 1`
    (`auto_root.py` only checks the output tokens, so a warning used to be
    reported as a verified deploy).
  - The label is set and **verified on `$D.tmp` before it replaces the live DLL**;
    aborting after the rename would have left the app unable to start (the
    2026-10-22 regression).
  - `share/mcs_orig.dll` / `mcs_ni_orig.dll` are created from a *known-stock*
    file when they are absent (md5-gated, with the md5 recorded in
    `mcs_orig.md5`/`mcs_ni_orig.md5`), because `uninstall.sh` hard-failed without
    them and no script had ever created them.
  - `rootchan.allow` is written before the DLL; `WANT=`/`SIZE_WANT=` are named
    constants.
- `server/uninstall.sh`: accepts a backup whose md5 matches the recorded
  snapshot (a non-retail TV can still uninstall), and a `LABEL_WARN` now aborts
  instead of printing `UNINSTALL_DONE`.
- `server/recover.sh`: prefers `deploy_local.sh`, otherwise rewrites `H=` inside
  the fetched `deploy.sh`; aborts (and says so) unless the deploy prints
  `DEPLOY_DONE`; the verify hint names `root_shell.py` instead of the non-existent
  `chan.py`.
- `tools/root_shell.py`: accepts `ROOT_TV` as well as `TV_IP` (the `.ps1`
  wrappers only set `ROOT_TV`), returns non-zero on a connection or protocol
  failure, and its docstring no longer says `chan.py`.
- `root.ps1` / `uninstall.ps1`: pass `$TvIp` to `root_shell.py` and check its exit
  code — the bare form exited 2, and `root.ps1` printed "Permanent root is up"
  without the check ever running. `uninstall.ps1` also declares `-NoServer`, adds
  the process-name check to `Stop-ToolkitServer`, and watches 31337 for the whole
  boot budget instead of 20 s (a still-booting payload could be reported gone).
- `root.ps1` no longer claims persistence it did not observe: it says plainly that
  `deploy.sh` restarted the app, so an open 31337 proves the payload runs, not
  that it starts at boot.
- `tools/run_root.py` / `auto_root.py` refuse commands over 509 B and
  `write_root.py` enforces 255 B paths / 4 KB chunks: the stub's `cmdbuf` is 512 B
  and it trusts the header, so a long command scribbled over adjacent stub data.
- `tools/tv_rootwatch.py`: finds an interpreter from `TVWATCH_PYSRV`/`PATH`
  instead of requiring the author's `pysrv.exe`, and loop mode now keeps watching
  after a successful `op 5` (it used to return 0 unless `--no-shell`).
- `tools/physmap.py`: the dead `root`/`rootexec` modes and `full_root()` are gone.
  They called an undefined `find_tasks_offset`/`walk_tasks`, required a firmware
  `uImage` that is not in the repo, and gated creds at `0xD0000000` while claiming
  success. `verify` no longer touches the uImage.
- `tools/physrpc.S` opens `/dev/video30`, matching the shipped blob. The source
  said `/dev/video40`, so a rebuild + re-embed would have silently switched device
  nodes; `--check-embedded` now catches that drift.
- `tools/smack_relabel.py` / `tools/find_task.py`: no hardcoded author paths,
  `find_task.py` defaults to the real comm (`DN_trol-Service`) and runs from a
  clone; both are labelled diagnostics (the supported path to the app label is the
  app's own channel).
- `tools/_selfroot.py` and `tools/taskwalk.py` are labelled DIAGNOSTIC, including
  the fact that `taskwalk`'s "next" is a guess, not a validated link.
- Docs: `AGENTS.md` v14 size/md5, the new channel-hardening facts, the payload
  invariants (close the fd in the child, `Sleep(700)`, `SaneCred`), the 509 B
  command limit, and `root_shell.py <TV_IP>` in every example; `README.md` payload
  row; `docs/SCRIPT-REVIEW.md` no longer claims `find_task.py` cannot run.

### Fixed

- **`root_via_fork` patched a freed task's cred pointer.** It looked up only the
  first `PHYSRPC1` task on `init.tasks.prev`; after an earlier page load that can
  be a dead thread, so the sane-cred check rejected its cred pointer six times
  (`skip 0xe234cf00 (not a cred)`) while the live stub sat further along the same
  list — the browser lane could not root at all. It now collects every tagged
  task (`_find_tags_near_tail`) and patches whichever validates;
  `tv_rootwatch.root_by_tail` got the same fix. Proven on a fresh stub: the live
  task was found on attempt 1 and patched immediately.
- **The gateway dropped a client that had just been paired.** The `RSET` peek set
  a 0.5 s socket timeout and only cleared it on success, so the timeout survived
  into the forwarding loop and the first idle read raised `socket.timeout` — the
  client was detached, `rpc_client` cleared, and the next client got the cached
  hello instead of `BUSY`. Caught by `tools/test_gateway.py`.
- `kernel_root.patch_full`'s uid readback (already fixed on 2026-10-23) is now
  covered by the extended `sim_rpc.py` self-test, together with the page-straddle
  case for the real scan generator.

### Deployed and verified on the TV

- `server/payload.dll` v14 deployed over 31337 at 15:09 (`SIZE=23040`, md5 match,
  `DLL_LABEL` verified, `BOOT_ROW_COUNT=1`, `AUL_RELOAD=ok`, `DEPLOY_DONE`).
- Cold boot verified with `systemctl --force reboot` from the root channel: the TV
  left the LAN, came back at +27 s and **31337 was open at +53 s** with v14
  (`uid=0`, `CapEff=0000003fffffffff`, DLL md5 `5b798012…`, app label correct).
  The boot beacon chain shows attempt 1 fast-exiting and attempt 2 rooting, as
  designed.
- Channel hardening proven on hardware: a 5,005-byte command line is rejected with
  `ERR command too long (5005 > 4096)`, and a silent client is dropped at 30 s
  while the next client is served at 31.3 s.
- **The real reason the TV looked unreachable:** Windows firewall has inbound
  *Block* rules for `python.exe`; the server had been started with `python
  server.py`, so the TV could not fetch the page and no beacon ever arrived, while
  the server looked healthy from the PC. Running it as `pysrv.exe` (the interpreter
  `root.ps1` already prefers) fixed both. This is now written down in
  `docs/OPEN-ISSUES.md` and `AGENTS.md` §1.
- Still open from the review list: binding 31337 to one address (`AGENTS.md` §11).
  Everything else was closed later the same day (below).

### Uninstall, backup creation and recovery — verified on the TV

- `uninstall.ps1 -NoWait` ran end-to-end: stock IL `f61f60dd…` and AOT
  `6c9bdcc4…` restored and relabelled, `BOOT_ROW=removed remain=0`,
  `UNINSTALL_DONE`, exit 0. It also demonstrated the fail-closed allowlist (#12):
  `uninstall.sh` deletes `rootchan.allow`, so the still-resident payload refused
  every later connection — correct behaviour, but it makes uninstall a one-way
  door until the next boot or a page load.
- With the stock IL/AOT back on disk and the backups deleted, the next deploy
  created them from scratch: `BACKUP_IL=ok`, `BACKUP_NI=ok`, md5s exactly
  `f61f60dd…`/`6c9bdcc4…`, recorded in `mcs_orig.md5`/`mcs_ni_orig.md5` (#3).
- `recover.sh` ran from the root channel: `RECOVER=deploy_local.sh` → deploy →
  `DEPLOY_DONE` → `RECOVER_DONE` (#5).
- A fresh browser page then rooted the stub and redeployed (the #4/browser path),
  and the final **mains power-cycle** boot confirmed v14 again: payload start
  20:23:41 → `SUCCESS-R00T` 20:24:05, channel up, `uid=0`, full caps.
- **Do not reboot the TV with `systemctl --force reboot` from the payload.** The
  first one worked; the second left the set in a deep standby that the remote
  could not wake, and only unplugging it from the wall brought it back. Ask for a
  power cycle instead (also recorded in `AGENTS.md` and `OPEN-ISSUES.md`).

### Stub hardening (#10/M3) and a test suite for other TVs

- **`tools/physrpc.S` now clamps everything the client controls.** READ requires
  `offset < 0x1000` and `offset+len <= 0x1000`; WRITE32 requires
  `offset <= 0xFFC`; READMANY caps the batch at 32768 pages; RUN caps the command
  at the 512-byte `cmdbuf`; FILE caps path 256 / data 4096. A refusal returns
  `-EINVAL`; for the two ops whose payload is already in the socket (RUN, FILE)
  the stub then exits, because parsing those leftover bytes as the next header is
  how a malformed request would otherwise turn into a corrupt write. The other
  three keep serving (no payload follows).
- Blob rebuilt 7440 → **7552 B**. Re-embedding is no longer a manual step:
  `tools/embed_physrpc.py` writes the array into `browser_payload.js` (refusing a
  staging overflow; `--check` proves page == blob), and
  `build_physrpc.py --check-embedded` proves blob == `physrpc.S`. Both pass
  byte-identical (`tools/physrpc_shellcode.bin` is committed so the check works
  without keystone).
- **Live-verified on the TV** (`tools/test_stub.py`): oversized READ refused with
  `-22` and the stub kept serving, cross-page WRITE refused with `-22`, overlong
  op 7 refused with `-22` and the stub ended; then `kernel_root.py --fork` rooted
  the same hardened stub and its op-7 shell returned `uid=0` with full caps.
- Tests for other TVs:
  - `tools/test_shell.py` — 17 dry checks of `deploy.sh`/`uninstall.sh` under
    `sh` with stubbed `chsmack`/`sqlite3`/`aulctl`/`curl`/`ls -lZ`/`id`: bad
    payload refused, label mismatch aborts before the rename and leaves the DLL
    intact, bad boot row aborts, stock backups created with md5 recorded,
    uninstall refuses missing/corrupt backups, restores + relabels, removes the
    boot row, aborts on label mismatch.
  - `tools/test_stub.py` — the live wire-contract + clamp layer.
  - `tools/test_all.py` — runs every layer; `--tv` adds the live stub;
    `docs/TESTING.md` documents each layer and how to port the suite.
- `tools/tv_ws_launch.py` — the Samsung remote-control WebSocket probe/launcher
  from the research tree, adapted into `tools/` (token under `server/logs/`,
  `--secure` for 8002). Its docstring records the measured result on this unit:
  `ms.channel.unauthorized` with or without the old token, so it is a diagnostic
  and a launcher for other sets, not a way in here.
- `tools/requirements.txt` gains `websocket-client`; `AGENTS.md` §5/§7/§11 and
  `docs/OPEN-ISSUES.md` point at the new suite.

### Second-pass review leftovers (PC-side)

An independent re-read of the landed fixes found four leftovers. Three are PC-only
and fixed here; the fourth needs a payload rebuild.

- **`tv_rootwatch.root_by_tail` could short-circuit on a stale tag.** It walked
  every `PHYSRPC1` task but returned `"already"` as soon as *any* of them had a
  uid-0 cred — a freed task's cred pointer can land on init's, or on a cred a
  previous run patched, and that hid a live uid-5001 stub. It now writes only a
  uid-5001 cred, remembers uid-0 tags without stopping, and reports `"already"`
  only when no uid-5001 cred exists. This is the watchdog twin of the
  `root_via_fork` first-hit bug; `tools/sim_rpc.py` grew two cases for it
  (stale-uid-0 tag → `"rooted"`, second pass → `"already"`).
- **`deploy.sh` did not abort when the stock snapshot failed.** `BACKUP_IL=fail` /
  `BACKUP_NI=fail` were warnings, so a failed `cp` could continue to `COPY=ok` /
  `DEPLOY_DONE` and re-open the "uninstall has no backup" hole the snapshot was
  added to close. Both now `exit 1` *before* the DLL is replaced, and
  `tools/test_shell.py` gained four checks (IL and NI snapshot failure: abort + the
  live DLL stays stock) using a `cp` stub that fails on demand.
- **`tools/_selfroot.py`** (diagnostic) now uses the multi-tag walk and only
  patches uid-5001 creds, matching the supported paths.
- **`SaneCred` still accepts uid 0** — `kernel_root._sane_cred` is a pointer
  validator, and the payload's call sites patch a cred whose uid is 0 *or* 5001,
  so a bogus `real_parent` that landed on init's cred would still be written (a
  near-no-op, but not ours). Closed properly in v15, below.

### Payload v15 — M4 closed, deployed and boot-verified

- `PatchCred` now refuses any cred whose uid is not **5001**, at the single choke
  point every call site goes through; a uid-0 cred counts as "already done" and
  is never written. `SaneCred` stays the pointer-shape check (range, alignment,
  usage, ids). The five call sites (`self`, `direct-parent`, the child-pointer
  scan) now only ask for uid 5001, so a bogus `real_parent`/`parent` landing on
  init's cred can no longer be patched. Same size, new md5:
  **v15, 23,040 B, `bf0c0342437c236c20ecaa0a8ee3bf4c`**.
- Deployed over 31337 (label verified, `COPY=ok`, `BOOT_ROW_COUNT=1`,
  `AUL_RELOAD=ok`, `DEPLOY_DONE`). Loaded with the documented `kill -9` path: AUL
  respawned the app in ~32 s, the beacon chain shows `direct-patch uid=0` (so the
  uid gate accepted the real cred and the patch still works).
- **Cold boot after a mains unplug**: round 0 fast-failed, round 1 rooted
  (`SUCCESS-R00T`, `ROOTCHAN 31337`) within ~33 s of the first probe;
  `uid=0`, `CapEff=0000003fffffffff`, DLL md5 `bf0c0342…`, boot row intact.
- `deploy.sh`'s `WANT=`/`SIZE_WANT=` and `AGENTS.md` §1/§7, `README.md` and
  `docs/OPEN-ISSUES.md` now carry v15.

### Payload v16 — 31337 binds one address, and the last item closes

- The listener no longer binds `0.0.0.0`. `RootChannel` derives the TV's own
  address from the **route to the recorded PC** (a UDP `connect` that sends no
  packets) and binds that. No IP is hardcoded, so another person's laptop needs no
  change: whichever address `deploy.sh` records is the one the bind follows. A
  wildcard listener was reachable from Wi-Fi Direct/tethering even though
  `PeerAllowed` filtered the peer; this keeps it off those interfaces.
- It **re-derives the address every 30 s** and rebinds if it moved (the accept
  loop polls `Pending()` so the check can run between accepts) — the failure mode
  a fixed bind would have had on a TV that changes address. With no route yet
  (TV offline at payload start) it falls back to `Any` and beacons
  `chan bind … failed`, then moves to the real address when one appears.
- Same behaviour otherwise. New size/hash: **v16, 24,064 B,
  `ef8721881df2903f36371aaa482eed9f`**.
- Live verification: after a `kill -9` reload and again after a mains cold boot,
  the beacon reads `ROOTCHAN 31337 uid=0 bind=<tv-ip>` and
  `/proc/net/tcp` shows `AFB2A8C0:7A69` LISTEN (<tv-ip>:31337), **not**
  `00000000:7A69`; `uid=0`, `CapEff=0000003fffffffff`, md5 match, boot row intact.

### Third pass — Python cred gate, bind fallback, comment

Three comments on the landed work, none of which reopen boot-to-root (PC-side
only; the TV was left alone):

- **`kernel_root.py --fork` wrote any sane cred, uid 0 included** — the
  browser-lane twin of the old M4 (the payload was gated in v15, the Python tools
  were not). New `kernel_root.patch_ours()` reads the uid first and only calls
  `patch_full` for 5001; a uid-0 cred is reported as "already uid 0 - nothing
  written" and never touched. `root_via_fork` and the legacy `root()` both use it,
  and `root_via_fork` now keeps scanning every target after seeing a uid-0 one.
  Two `sim_rpc.py` cases prove it: a uid-0 cred is left byte-identical, a
  uid-5001 cred is patched, a foreign uid (1234) is skipped.
- **`ListenOn`'s `Any` fallback** (specific bind failed, e.g. the address is not
  up yet) leaves the wildcard open for up to 30 s. Accepted, not reverted: it
  only happens when the TV has no route at payload start, the beacon records it
  (`chan bind … failed`), and the 30 s re-derive moves the listener to the real
  address. The common case (address present) binds the LAN address immediately.
- **Glued comment in `Program.cs`** (two sentences merged) fixed. Comments do not
  enter the IL — both versions build to the same hash — but a rebuild still
  differs from the committed `server/payload.dll` because the SDK embeds the git
  SHA in `AssemblyInformationalVersion` (`1.0.0+<sha>`). That is why a rebuild's
  md5 must drive `WANT=`/`SIZE_WANT=`; noted in `AGENTS.md` §9, with
  `IncludeSourceRevisionInInformationalVersion=false` as a v17 candidate for
  reproducible artifacts.

---

## 2026-10-23

An independent code review landed: `tools/sim_rpc.py` plus a `patch_full` fix, the
triaged work list in `docs/OPEN-ISSUES.md`, and the repo hygiene below.

### Added

- `tools/sim_rpc.py` — in-memory physmap RPC (read/write32/readmany) so
  `kernel_root.patch_full`, `_sane_cred` and the owner-cred scan pattern can be
  exercised without a TV. The research QEMU kernel never reached userspace, so
  this is the offline stand-in; `python tools/sim_rpc.py` is the self-test.
  Layout constants match the TV and the pontusml DWARF dump (`cred.uid +4`,
  `cap_inheritable +0x28`).
- `CHANGELOG.md` (this file), plus a rule in `AGENTS.md`: any future change must be
  recorded here with its reasoning. The dated narrative that had accumulated in
  `AGENTS.md` and the docs now lives here; those files describe the current state and
  the how, not the history.

### Changed

- `AGENTS.md` gained a "Maintaining this repo" section defining that split, and the
  narrative history paragraph became a pointer to this file.
- `README.md` documentation index lists the changelog.

### Fixed

- `kernel_root.patch_full` verified uid by reading `cred+40` (`cap_inheritable`)
  instead of `cred+4`. The ids and caps were already patched; a non-zero
  inheritable made `--fork`, `tv_rootwatch.py` and `scan_cred.py --patch`
  report failure and skip the shell. Readback now uses uid at +4 and the
  named cap offsets.
- **`server/index.html` was the pre-fix copy.** The service-worker unregister, the
  dynamic `?v=` cache key and the `RUNNING_AT` marker existed only in the working
  tree used for testing; the shipped file still loaded
  `lib/wasm_builder.js?v=5`. The tested page is now in the repo (this is the bug
  that once made the TV run a stale builder and die before logging).
- **Repo hygiene:** `payload/out10`–`out13` (16 build artifacts, ~690 KB) were
  committed by accident; they are untracked again and `payload/out*/` is ignored
  (only `server/payload.dll` is tracked). Stale constants fixed: `AGENTS.md` said
  payload "v7", 36 files and `SIZE=17920`/`d247e67a…`; `.gitignore` said 18 KB;
  `docs/SCRIPT-REVIEW.md` and `docs/PORTABILITY.md` implied
  `smack_borrow.py`/`dwarf_offsets.py` ship in `tools/` (they do not).
---

## 2026-10-22

The day the mechanism was proven, broken, and proven again — and the repo was made
readable.

### Added

- **Host-independent operation (v10).** The toolkit no longer assumes the author's
  LAN:
  - the exploit page **rewrites the shellcode's callback address at runtime** from
    `location.hostname`, so the browser stage connects back to whichever PC served
    the page (no rebuild needed);
  - `deploy.sh` records the PC address in `share/rootchan.host`, and the payload
    (v10) reads beacons' destination from it, falling back to the compiled-in
    default;
  - `server/recover.sh` takes the PC address from that file (or an explicit
    argument) instead of a hardcoded default;
  - `tools/root_shell.py` requires a TV address (`argument` or `TV_IP`) rather than
    silently using the author's.
  Payload v10: 20,480 B, md5 `e45e53b6e20925521dee954ec2a1d1d8`. Verified: booted
  and rooted (71 s on that boot, via the direct-parent path), beacons reached the
  PC, `rootchan.host` present.

- **Persistent root, twice over.** The boot payload roots the TV at every boot and
  serves a command channel on TCP 31337. It was achieved with payload v5, re-verified
  after a boot regression with v7, and made fast with v9 (~40 s from power-on, with
  no PC or browser involved). After the payload was removed to test the undo path it
  was reinstalled and verified again on a cold boot.
- **`server/recover.sh`** — one command, run from a root shell on the TV, that takes
  the app's SMACK label and reinstalls the payload end to end.
- **`docs/SERVER-HOSTING.md`** — how the PC-side server must run, and the silent-death
  trap described below.
- **`docs/PORTABILITY.md`** — the four gates for another Tizen 9 TV: browser, physmap,
  kernel constants, on-boot carrier; what to re-measure and what transfers unchanged.
- **`docs/USAGE.md`** — the operational detail that used to clutter the README:
  options, the two TV-side steps, expected output, host-IP caveat, uninstall
  behaviour, manual fallback, common failures.
- **`server/probe.html`** — a zero-risk probe for a foreign unit: reports the user
  agent, Chrome version and real WasmGC support (it validates a struct-type module),
  and executes nothing.
- **`tools/dwarf_offsets.py`** — reads struct offsets from a kernel build's DWARF.
  Four of the offsets it produced matched the TV exactly (`comm +0x400`,
  `cred +0x3F8`, `real_parent +0x2F0`, `tasks +0x23C`), which is what made it a
  trustworthy layout source.
- **`tools/find_task.py`** — resumable physical scan for a task comm; reconnects and
  continues after a desynced batch instead of restarting.
- **`tools/tv_rootwatch.py`** — host watchdog: starts the server if needed, roots the
  exploit stub, and hands back a root shell on `127.0.0.1:9999`.
- **`tools/smack_relabel.py`, `tools/smack_borrow.py`** — the kernel-memory label
  approach, kept because the diagnosis is instructive even though it was not needed.

### Changed

- **Docs reviewed one by one and repaired.** `docs/BOOT-REGRESSION-SMACK.md` was
  corrupt (an earlier edit had spliced a correction note and PowerShell fragments
  into the middle of a sentence) and was rewritten. `docs/FAILED.md` had three
  overlapping SMACK sections, now one that tells the story in order. `docs/SCRIPT-REVIEW.md`
  had become a second changelog, so it is now an actual review of the scripts (issue
  table, race status, limitations, validation). `docs/SERVER-HOSTING.md` pointed at
  paths that were not in this repo, so `server/run_server.cmd` and
  `server/run_server.vbs` now exist here, and the interpreter is configurable via
  `TV_PY`. `AGENTS.md` §1 was the same story twice plus payload lineage; it is now a
  compact current-state section, and §10/§11 lost two factual errors and a duplicated
  analysis.
- `docs/EXPLOIT.md`: the address-space paragraph was wrong (it claimed the linear map
  covers up to `0xFFFFFFFF`), which is exactly the trap that made a vmalloc label
  lookup look like "not found". It now separates the linear map from vmalloc and says
  why the physmap can only translate the former.
- **README rewritten for readers** (265 → ~140 lines): what the project is, current
  state, quick start, four-line summary of the chain, documentation index, layout,
  requirements, compatibility, safety. The deep content moved into `docs/`.
- **`root.ps1` now injects a relabel prelude** into the generated `deploy_local.sh`.
  Without it the automated path deployed from the browser-labelled stub, whose SMACK
  label cannot write the app's `bin/`, so it always ended in `COPY=fail`.
- **`deploy.sh` restarts the app detached** — `aulctl stop` blocks while the payload
  is running (it waits for the app to exit), so the script used to hang before
  `DEPLOY_DONE`. It now runs `( sleep 1; stop; sleep 3; start ) &`.
- **The server runs as a scheduled task** (`TV-LabServer`) launched through `wscript`,
  so no console owns it.
- **The deploy and uninstall scripts verify their SQL** instead of trusting it: they
  read `boot_sequence` back (`BOOT_ROW_COUNT=1`, `remain=0`) and fail loudly.
- **Documentation rewritten for timelessness**: prose no longer carries timestamps;
  the history is this file.

### Fixed

- **Payload v12: the command channel can no longer be wedged.** `Run()` read the
  command's output through a pipe (`ReadToEnd()`) and only checked the 15 s timeout
  afterwards, so a grandchild that outlived the timeout kept the pipe open and
  blocked the single-threaded server forever — measured: one `grep -r /opt` made the
  channel deaf until a power-cycle. Output now goes to a temp file and the timeout
  kills the whole process tree; a runaway command returns
  `[timeout: killed after 15s]` and the channel keeps serving (verified with
  `sleep 40`).
- **Payload v13: auto-update is pinned off at every boot.** The TV's own update
  machinery (`swu-auto-upgrade.path` → `org.tizen.tv.swu.otascheduler`) would
  replace the app the payload lives in. The payload now re-asserts
  `db/menu/support/softwareupdate/autoupdate = 0` (system and user layers) via
  `buxton2ctl` and beacons the readback. The value was already 0, so this is
  enforcement rather than a change of state; verified after a reboot
  (`DSHROOT autoupdate … = Int32: 0`). Payload: 21,504 B, md5
  `176914345bcc81ca8c87de712b4a044f`.
- **Payload v11: a slow boot is now half as slow.** A boot whose task list is
  unreadable used to spend 20 s per failed round waiting for a landmark it could
  never see, plus 14 s scanning a landmark that reads back stale — 65 s before the
  channel appeared. Both budgets now give up early in fast mode (3 s landmark wait,
  5 scans) and let AUL relaunch a fresh process instead; the long fallback keeps the
  patient values. Measured on the same class of bad boot: **34 s instead of 65 s**
  (rounds fail in ~4 s, three attempts were needed). Payload: 20,480 B, md5
  `b0831d7abbfb25eab17f06186b29f41c`.
- **The blank exploit page had two causes, both on the PC.** First, the server was a
  console program under a job or Task Scheduler: when that console went away Windows
  terminated it with no traceback, and the page lost its endpoints a few seconds after
  loading. `safe_accept()` now wraps every `accept()` so a transient error cannot end
  the process, and the launcher keeps stderr in `logs/server.task.err`.
- **The page could run a stale builder.** `lib/wasm_builder.js?v=5` was a static cache
  key, so the TV could execute an old builder against a current payload and die before
  logging anything. Both scripts are now cache-busted, service workers are
  unregistered, and a `RUNNING_AT` marker separates "crashed inside the exploit" from
  "never started".
- **`RSET` raced the page.** The client helper resent `RSET` on every failed attach, so
  a stub that connected between two attempts was destroyed instantly, and the server
  also evicted clients that were merely waiting. Both sides fixed: the client does not
  reset while waiting, and the server only evicts a client that is actually paired.
- **`uninstall.sh` looked successful after a no-op delete.** It now reads the table
  back and aborts if the row survived.
- **The payload's SMACK label regression (the boot-persistence bug).** The DLL written
  by the browser stub carried the *browser's* label, so the app was denied read on its
  own assembly and died before `Main`. The fix — `chsmack` the app's `::RO` label after
  every copy, with a verified readback — is in both deploy and uninstall.
- **Payload v9: 11 minutes to root became ~40 seconds.** The first launch after a cold
  boot cannot read the task list reliably; v9 gives up quickly and lets AUL relaunch a
  fresh process instead of sleeping in the failed one.
- **Payload v6: warm-restart failures.** It snapshots existing `PHYRFORK` landmarks,
  waits for a *new* one, validates the cred before patching, and excludes stale
  orphans (`kill -9` of the app now re-roots in 8–11 s).
- **Payload v5: `fork()` copies the credential.** Patching a child's cred never roots
  the parent; the parent must be found through the child's `real_parent`. Also
  `Kptr()` had to accept addresses above `0xE0000000` — this LPAE kernel allocates
  tasks and creds there.
- **`deploy.sh` printed `COPY=ok` while every `cp` failed**; it now checks and aborts.
- **`readmany` desynchronised the stub** whenever a batch hit an unmappable page: the
  stub aborted the batch while the client kept reading, so every later read returned
  garbage and a scan looked like a clean negative. The client now stops at the bad page
  and restarts after it.

### Removed

- **Date/time stamps from the prose** (kept: a quoted TV log line, two external lab
  filenames, and a `schtasks /ST` argument).
- **The dated filename** `docs/BOOT-REGRESSION-SMACK-2026-10-22.md` → `BOOT-REGRESSION-SMACK.md`.

### Discovered (recorded in `docs/FAILED.md` so nobody repeats them)

- The **userspace relabel works**: a root shell can take the app's label with
  `echo -n "User::Pkg::<appid>" > /proc/self/attr/current`. That single fact replaced
  the kernel-memory relabel entirely and was what restored the payload.
- **Kernel-memory relabelling is impossible on this unit**: the `smack_known` struct
  lives above `0xE0000000` (vmalloc), so `phys = va - 0xA0000000` does not apply and
  the physmap cannot read it. 635 copies of the label string exist in the direct map
  and none is pointed at.
- **The app's process `comm` is `DN_trol-Service`**, not `MultiControl*` — every
  physical scan for the app was searching for a name that never exists.
- **The app is invisible in the browser shell's PID namespace**, so `/proc` looks empty
  while `aulctl status` reports it running.
- **`aulctl reload` does not restart a running app**; only stop+start does.
- The app lane is write-protected by label, not by permissions: the shipped SMACK
  policy grants no `User::Pkg::*` access to `User::Home`, so only the app's own label
  can write its files.

---

## 2026-10-21

### Added

- **Permanent-root design**: an on-boot service app on the writable `/opt` partition,
  running the V4L2 physmap chain at every boot. Confirmed live: `owner` is in group
  `video`, and 16 apps carry `app_onboot='true'`.
- **Boot-hook map** and a firmware-derived understanding of the boot chain: `systemd` is
  PID 1, `rc.sysinit` never runs, and the only exploitable boot hook is the app lane.

### Discovered (all negative, all recorded)

- **UEP blocks unsigned execution** on the shipped kernel, including tmpfs and memfd
  tricks that the GPL source suggests should work.
- **`sdbd root:on` is a dead end**: it compares a cached capability string that the
  shipped plugin never fills.
- **systemd does not read `/opt` units or drop-ins**, and D-Bus `StartTransientUnit`
  from uid 5001 is denied.
- The installer's absolute-path extraction creates **new files only**; it cannot
  overwrite the app's DLL.

---

## 2026-10-20

### Added

- **Browser code execution on the TV** (uid 5001) through CVE-2024-2887 (WasmGC type
  confusion) in Chromium 120, with the six firmware-specific ROP constants measured
  rather than copied.
- **Root** through the V4L2 physmap: `/dev/video40` passes an attacker-chosen
  `vm_pgoff` to `remap_pfn_range()`, giving arbitrary physical read/write from an
  unprivileged process in group `video`. Kernel Image at phys `0x20008000`,
  `init_task` at `0xC0957180`.
- **Firmware decryption and extraction** (MSD 1.1 key, VDFS4 partitions), which is what
  made the kernel layout, SMACK policy and boot chain knowable at all.

### Discovered

- The sdb route is dead on this firmware: the shell is whitelist-only and the
  published injection does not execute. The browser route needs no sdb and is the one
  that worked.
- The GPU CVEs in scope for the reported DDK version cannot apply: the GPU is a
  Mali-G51 Job-Manager part, and the vulnerable code paths are CSF-only.
