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

The repo is green offline (`python tools/test_all.py`, 11/11 layers) and
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
5. **Reference-derived follow-ups, in value order:** a per-run task tag
   (`PHYSRPT`+pid) plus a pid/tgid and `real_cred == cred` check to retire the
   stale-task family for good; OTA hardening beyond the buxton key
   (`/mnt/backup/OS_UPGRADE_FLAG` + `systemctl mask --runtime` for
   `swu-auto-upgrade.*`, `fw-update-service.*`, `fw-usb-update-service.*`,
   `was-background-update.*`).  (Done: the DWARF offset reader, the
   layout-shift-proof list walk, the sanitizer - see `tools/` and
   `docs/REFERENCE-MATERIALS.md` for the download sources they assume.)
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
   6 files tracked since 1b05289 despite the .gitignore rule) ships. Also at
   publish time: blank `beacon_token` in `docs/state.json` (`--fix`) or leave
   it - it is LAN-local and rotates on every deploy.

## Deliberately deferred

Reviewed and consciously not done - listed so the next session does not
rediscover them:

- **Per-run tokens: done in two halves** (PGDB stub hello v40, DSHROOT beacon
  v41, both live-verified).  Residue, kept deliberately: a token-less beacon's
  *content* still reaches `beacons.log` so a legacy/pre-deploy payload stays
  diagnosable; admission to the shell slot is fully gated.
- **A `tools/` constants module.** Offsets/limits are duplicated across
  `Program.cs`, `sim_rpc.py`, `kernel_root.py`, `physmap.py`, `physrpc.S`, the
  page and `deploy.sh`; `test_constants.py` catches drift. Deferred: touches
  every tool for no behavioural gain on this unit.
- **Splits:** `server.py` into client/gateway/http modules, a threaded accept
  loop, `sim_rpc.py` / `Program.cs` partials. Offline tests exist; the
  refactors are riskier than their value until the hardware lane demands them.
  When it happens: fix order is local P1s first, then extract `ShellChannel` /
  `RpcGateway` classes keeping every wire byte and log token identical
  (`tools/test_gateway.py` is the oracle), thread `serve_http` last - and do
  not migrate frameworks, the raw-socket peer classification is the
  load-bearing part.
- **Remaining research ports:** `taskwalk.py` orphan detection, a QEMU/softmmu
  physmap harness, a C `cred_scan` utility - porting investments, not
  this-firmware work.
- **High-PA deliberate read:** one falsifiable check left from the memory-model
  work (`AGENTS.md` §11); the zoneinfo boundary is already measured.
- **Encoding hardening beyond stdout:** TV-facing stdout already uses
  `errors="replace"` (a locale console used to crash the reporting tools on
  non-ASCII bytes), but a few tool file reads/writes still rely on the locale;
  pin `encoding="utf-8"` when touching them.

## Closed history

The per-finding record of the 2026-10-23..26 review passes (P0/P1/P2 tables,
the five boot-tuning passes, environment notes) is archived in
[`docs/REVIEW-HISTORY.md`](REVIEW-HISTORY.md); dated narrative in
`CHANGELOG.md` (older passes: `docs/CHANGELOG-ARCHIVE.md`).
