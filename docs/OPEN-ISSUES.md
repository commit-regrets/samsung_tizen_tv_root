# Open issues — current state, pending work, and closed history

> **RESOLVED 2026-10-30:** SmartThings showed the TV offline because
> `org.tizen.easysetup-daemon` was disabled. Phone-confirmed both ways:
> that one disable flipped it offline, and re-enabling it brought the phone
> back **online** (~18:51). Denylisted, and its unit is off the mask list.
> Step log:
> [docs/SMARTTHINGS-OFFLINE-2026-10-30.md](SMARTTHINGS-OFFLINE-2026-10-30.md).

## Current state — 2026-10-30 (v42 verified: cold boots, 29-unit durable masks,
37 app rows, SmartThings phone control confirmed online; test_all 14/14)

TV: **v42** (`cbf8f293…`, 39,936 B), rooted via 31337. Every beacon carries
`tok=<BEACON_TOKEN>` (from `rootchan.token`); forged and token-less beacons are refused.
`id -u` = 0, `CapEff=0x3fffffffff`.
**All hardware gates are closed (2026-10-27):** v41 cold boots at **36 s**
(attempt 1 fast-exit t=29, attempt 2 direct-parent t=36) and **49 s** after the
recover cycle (AUL launched late; one direct-patch attempt); `kill -9` recovery
**~2 s**; uninstall verified (stock IL `f61f60dd…`, AOT `6c9bdcc4…`, boot row 0,
allow removed, 31337 stayed closed after a cold boot, stock 9197 back); recovery
via `recover.sh <pc-url>` completed `DEPLOY_DONE`/`RECOVER_DONE` and the following
cold boot rooted again.
Backups: `mcs_orig.dll` (stock), `mcs_ni_orig.dll`, `payload_backup.dll` = v41.

The repo is green offline (`python tools/test_all.py`, 13/13 layers incl. the
debloat tooling layer) and
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
5. **Debloat — durable; service suppression is live (RESOLVED 2026-10-30).**
   **37 apps are durably disabled** (`pkgcmd --global`; 10 from tier 1, 5
   from tier 2a, 22 voice ids from batch 3) and **29 units are on the mask
   list**, re-applied at every boot by the payload from
   `/opt/usr/data/debloat-masks.txt`.  Two ids are **not** among them and
   never will be, both phone-confirmed: `com.samsung.tizen.samsung-analytics`
   (the SES privilege provider `smartthings-client` requests) and
   `org.tizen.easysetup-daemon` - disabling that one alone flips the phone
   from online to offline (owner-confirmed bisect 2026-10-30). The 16
   sharing ids stay reverted (prudence, not the cause). **Cold-boot acceptance PASSED
   2026-10-30 14:05:40** (mains cycle, no PC involved): `masks=24 stopped=24
   killed=3 fail=0 missing=0 listed-activating=0 loop-check=ok
   newhome=set(0),loop-started` at t=51 s, every unit masked-runtime and none
   active, zero processes under the listed binaries, 20 app rows true, both
   sentinels present. **Extended the same day to 34 units / 26 binaries** with
   the OTA / firmware-update stack (see item 6): `masks=34 stopped=34 killed=1
   fail=0 missing=0 activating=0 listed-activating=0 loop-check=ok
   newhome=set(0),loop-active`, and a **second restart loop**
   (`vdsystem-update-manager.service`, `Restart=always`) was found and stopped
   by it. Later that evening the list was cut to **29 units / 23 binaries**
   (the four phone-path units plus the `org.tizen.easysetup-daemon.service`
   mask, all removed for SmartThings), and the 37-row / 29-unit standing set
   was applied live at 18:56: `masks=29 stopped=29 killed=4 fail=0 missing=0
   activating=0 listed-activating=0 loop-check=ok`, SmartThings stack alive,
   phone **online** (owner-confirmed). Design: `debloat/models/qnx1d/v42-design-brief.md`
   (reviewed, cleared, implemented as `MaskServices()`); the two policy files
   are installed by `deploy.sh` and deleted by `uninstall.sh` — that is the
   revert. **History:** round 4 (2026-10-29) masked 23/23 during that session
   (`~192 MB` sum-RSS upper bound); the 24th (`org.tizen.easysetup-daemon.service`,
   `NRestarts=654`) was added 2026-10-30 and **removed again the same evening**
   (that daemon must keep running for SmartThings phone status, and masking its
   unit stops it just like the app disable does); before v42 a reboot cleared
   the masks, which is why the 12:35 reading that day was "one mask up". Both pre-checks are closed
   (2026-10-30): (a) the mains cycle
   read back **all 20** `app_disable='true'` rows with both sentinels present and
   `id -u` = 0, so the store is durable as-is; (b) `bluetooth-monitor.service` is
   **excluded from the mask list and the kill list on the owner's instruction** —
   it is the boot-time Bluetooth re-activator (unit comment: "check previous
   BT-connection status and re-activate BT when boot"; wanted by
   `starter.target`; `bt-monitor` holds `/dev/micom-msg` and `/dev/eeprom`;
   `Restart=on-abnormal`, 2 s). tcc blocks it and reports the remote still
   works, but that is unverified on this set; the owner wants Bluetooth left
   alone and ~5.8 MB is not worth the experiment. Placement/state:
   `debloat/AGENTS.md`.
6. **Reference-derived follow-ups, in value order:** a per-run task tag
   (`PHYSRPT`+pid) plus a pid/tgid and `real_cred == cred` check to retire the
   stale-task family for good.  **OTA hardening: the mask half is DONE
   (2026-10-30)** - `swu-auto-upgrade.*`, `was-background-update.*`,
   `vdsystem-update-manager.*`, `swu-verifier-tv.*`, `swu-core-tv.service`,
   `swu-service.service`, `vdca-update.service` and the already-listed
   `fw-update-*` units are all on the durable list (29 units after the
   phone-path and easysetup drops).
   `fw-usb-update-service.{service,path}` does **not exist on this unit**
   (checked 2026-10-30: no unit file, `is-enabled` errors) - if a future
   firmware ships it, add it there.  **The five tcc service candidates are
   measured and REJECTED (2026-10-30):** sum-RSS ~35.5 MB, but PSS is 1.77 MB
   (`slive-provider-daemon`) + 1.01 MB (`screen_sharing`) + 0.49 MB
   (`user-presence`) + 0.08 MB (`wifi_state_manager`, whose unit is
   `wsm-service.service`) = **~3.4 MB**, and `mcf-agent-service` is an app
   (`app_launcher -s com.samsung.tizen.mcf-agent`), inactive at the time.  The
   Wi-Fi state daemon must not be touched while the root channel rides the
   network.  **The vendor flag lever is REJECTED:
   `ConditionPathExists=!/mnt/backup/OS_UPGRADE_FLAG` resolves to
   `/mnt/systemrw` (trap 9) - do not plant it.**  (Done: the DWARF offset
   reader, the
   layout-shift-proof list walk, the sanitizer - see `tools/` and
   `docs/REFERENCE-MATERIALS.md` for the download sources they assume.)
7. **Public-release hygiene** — `LICENSE` (MIT for original work), `NOTICE.md`
   (third-party browser chain is not relicensed; the vendored Vetro catalog
   under `debloat/third_party/vetro/` is MIT and now listed there), logs and
   build output ignored,
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

## New falsifiable checks — from the tizen-tv-control-center cross-reference

An independent S90D project (EU, **T-PTMxxxx** — the same firmware family as
this unit) runs root commands **over SDB** with Developer Mode enabled, and
replaces `/opt/etc/parseinfo.sh` wholesale as its persistence boot hook. Both
conflict with our recorded findings and are cheap to settle now that we hold
root (no Developer Mode needed to flip the switch ourselves):

1. **SDB root-exec on our unit.** Our `FAILED.md` closed `sdbd root:on`
   (capability 10005 unimplemented) — measured with Developer Mode OFF. The
   S90D project uses Developer Mode + SDB + a community root tool on the same
   firmware family. Check: enable Developer Mode via the buxton keys we found
   (`db/sdk/develop/{mode,ip}`) from the root shell, `sdb connect`, and re-run
   the sdbd probes. If it opens, SDB becomes a redundant transport (their
   chunked base64 push/pull mirrors our `write_root`).
2. **`parseinfo.sh` as a second persistence hook.** Our `FAILED.md` says
   editing it broke the boot service (UEP-signed file). Their S90D replaced it
   wholesale with an unsigned script and it runs as root at boot. Check:
   re-inspect our stock file's UEP appendix vs theirs, and whether the boot
   runner executes an unsigned replacement (test with a no-op echo appended,
   observe `/proc/target_version`, revert immediately).

Both outcomes are useful: either our dead-end record gains a
Developer-Mode-ON correction, or we gain a second root transport and a simpler
persistence hook — on the same firmware family either way.

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
