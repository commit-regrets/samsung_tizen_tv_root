# Open issues — current state, pending work, and closed history

> **RESOLVED 2026-10-30:** SmartThings showed the TV offline because
> `org.tizen.easysetup-daemon` was disabled. Phone-confirmed both ways:
> that one disable flipped it offline, and re-enabling it brought the phone
> back **online** (~18:51). Denylisted, and its unit is off the mask list.
> Step log:
> [docs/SMARTTHINGS-OFFLINE-2026-10-30.md](SMARTTHINGS-OFFLINE-2026-10-30.md).

## Current state — 2026-11-05 (TV runs v48; 73 app rows; 29-unit durable masks; SmartThings online; all hardware lanes green)

TV: **v48** (`bf3df7dc…`, 43,008 B), deployed 2026-11-04 22:01 and cold-boot
verified 22:11. Rooted via 31337. Every beacon carries `tok=<BEACON_TOKEN>`
(from `rootchan.token`); forged and token-less beacons are refused. `id -u` = 0,
`CapEff=0x3fffffffff`. See `CHANGELOG.md` 2026-11-04 for the v48 deploy and
2026-11-05 for batches 4–6 and the live re-run.

**v48 cold boot (2026-11-04 22:11, mains cycle):** launch t=28 s (attempt 1
`high-alloc … fast-exit`), attempt 2 `direct-patch uid=0` t=36 s, `ROOTCHAN`
t=36, `masks=29 stopped=29 killed=4 fail=0 missing=0 activating=13
listed-activating=0 loop-check=ok newhome=set(0),loop-started` t=42; both
starts `art=bf3df7dc…`; `tv_health` 16/16; zero `counter-write-failed` lines.

**Debloat:** **73 app rows** (tier 1 10 + tier 2a 5 + voice 22 + batch 2 29 +
batch 4 game trio 3 + batch 5 leftovers 3 + batch 6 utterance core 1) and
**29 units / 23 binaries**. Batch 4 (game trio, 69 rows) applied 2026-11-05
12:21, cold-boot passed 12:31. Batch 5 (`ghdaemon`/`ghservice` + Screen
Mirroring, 72 rows) applied 12:33 and batch 6 (utterance core, 73 rows) at
12:39; both cold-boot passed 12:59 (attempt 2 t=71; masks 29/29; `tv_health`
16/16). Remaining: the 17 tier-2b ids need the Control Center layer or owner
decisions; `tagpro-service-tv` is deferred (2026-11-05); HbbTV, Cobalt and AI
Sound are non-removable. Screen Mirroring's re-disable was phone-tested
2026-11-05 (SmartThings online with it disabled). Details:
`debloat/AGENTS.md`, `debloat/registry.tsv`.

**Live hardware layer re-run 2026-11-05:** `tools/test_all.py --tv --tv-ip`
passed all **19 layers**; `stub-protocol` OK and `tv-health-live` 16/16. The
offline suite is 17/17 and `sanitize_for_public.py --check` is green.

Earlier hardware gates (v41, 2026-10-27): cold boots 36 s and 49 s; `kill -9`
recovery ~2 s; uninstall and recover verified (stock IL `f61f60dd…`, AOT
`6c9bdcc4…`, boot row 0, allow removed, 31337 closed after a cold boot, stock
9197 back). Backups: `mcs_orig.dll` (stock), `mcs_ni_orig.dll`,
`payload_backup.dll` = **v47** (`0df29b15…`, the v48 deploy's `PREV_IL`).

The kernel memory boundary is zoneinfo-derived (`max_low_pfn 0x50400` →
`high_memory` VA `0xF0400000`) and the full physical map is measured (the
156 MiB no-map carve-out at PA 0x40000000-0x49C00000 explains every "high-half"
read failure; the meminfo-derived `0xE4E42000` was wrong, vendor-adjusted
counters): see item 2.

**Current pending work (the v44–v46 paragraphs below are closed history, kept for reference):**

- **Portability** — no second model/firmware tested; the four gates in
  `docs/PORTABILITY.md` are still unproven elsewhere (item 4).
- **Public-release hygiene** — git history still contains private tokens
  (real IPs, model/firmware strings, the device DUID); decide whether
  `.zcode/` ships; blank the beacon token at publish (item 7).
- **Debloat remainder** — the 17 tier-2b Home/TV Plus/Health/TAP/Art/coupled
  ids need the Control Center layer or owner decisions; `tagpro-service-tv`
  is deferred; HbbTV/Cobalt/AI Sound are non-removable (item 5).
- **Docs freshness** — this file was refreshed 2026-11-05; `HANDOFF.md` still
  has a 2026-11-01 header (its body is current).

**Closed history — v44–v46 deploys (kept for reference):**

**~~Owed: deploy v44~~ — done 2026-11-01** (over 31337, `COPY=ok`,
`DEPLOY_DONE`, cold boot passed the same afternoon). The follow-up review fixed
the launcher gate it exposed: `root.ps1` now waits for `id -u` = 0 through
`tools/wait_rooted.py` instead of trusting a port probe (the deploy's kill is
detached, and the dying old app's listener answered the probe while the new
payload hunted for five minutes), and `deploy.sh` clears `/tmp/.dsh_try` before
its restart so a deploy after a bad boot gets a fresh fast budget.
**~~Residual: `RESTART_KILL=` / `RESTART_START=` vanish into `/dev/null`; "old
app never died, new DLL not loaded" passes the `id -u` gate~~ — done, built +
offline-verified, deployed 2026-11-01 21:01 and cold-boot accepted 21:10
(repo v46/v46.1).** The restart
subshell now writes to `share/restart.log` (echoed `RESTART_LOG=`) and
`tools/wait_rooted.py` reads it back after a rooted answer; the payload beacons
`art=<md5>` (read once at startup from the deploy-rendered `rootchan.art`) on
its start beacon, so `beacons.log` proves which DLL each process started with.
**Deployed 2026-11-01 21:01 and cold-boot accepted 21:10** (both launches
carried `tok=` + `art=c540a6ab…`).
**v46.1, after the second review (2026-11-01):** the freshness proof uses TWO
witnesses — the newest launch's `tok=` against the deploy's `TOKEN_FILE=` (the
token is rendered fresh per deploy, so this survives redeploying identical
bits, which the md5 alone cannot) **and** its `art=` against `ART_FILE=` (which
DLL it read); `root.ps1` gets the "newest launch" from
`tools/beacons.py --newest-start` instead of rescanning, and `wrc=3` now exits 3
instead of claiming success. `deploy.sh`'s rollback removes `rootchan.art` /
`restart.log` only when THIS attempt wrote them (`ART_WRITTEN` /
`RESTART_ARMED`) — it used to delete the previous deploy's still-accurate marker
when a failure landed before the write. **The live proof is in** (deploy 21:01,
mains-cycle boot 21:10: both fresh launches carried `tok=<deploy token>` and
`art=c540a6ab…`, and `root.ps1` printed the `proven` line). The artifact-md5
beacon was designed fresh in
v46 — it was never a proposal in `docs/V45-BLIND-WALK.md`.

**v45 — deployed and cold-boot verified 2026-11-01.** Exit long mode on a
rootless pass (any pass, not only a blind one — the 2026-11-01 pass had latched
its child and was still stuck), capped at 3 exits per boot, beacon
`long-exit attempt=N count=K`. Deploy over 31337 (md5 `35cc7577`, `COPY=ok`);
the deploy relaunch rooted in 10 s, and the mains-cycle boot rooted on attempt 2
at t=37 s with `masks=29 … loop-check=ok` at t=44 s and **no `long-exit`
line** — the normal path is untouched. Rationale and the criterion correction:
[`V45-BLIND-WALK.md`](V45-BLIND-WALK.md).

**Follow-up 2026-11-01 - fixed and now pinned by tests:** the beacon-token set
did not survive a **PC-server restart**, so a deployed payload's beacons were
refused *and never reached `beacons.log`* (the "no beacon = AUL never launched"
misread). It is persisted in `logs/beacon-tokens.json` and reloaded at start.
The same pass added the tests that would have caught it and the other
review findings: `test_gateway` (token trim + restart, abandoned-waiter slot,
all mutation-checked), the new `test_server_unit` (deny-path class table,
traversal, token save/reload, best-effort `log()`, the request deadline), the
new `test_hygiene` (every `.py`/`.json`/`.sh` parses; LF/BOM/shebang), the
uninstall label prelude in `test_shell`, and the twin's unreadable-comm `break`
in `sim_rpc`. `mask.sh`'s summary key `start-failures=` was renamed `fail=`
(it has counted stop failures since the second pass). `AGENTS.md` §9 now records
the deliberate self-side rank-1 floor.

**Second pass 2026-10-31 - fixed:** the debloat scripts' four silent-success
paths (undo log, sentinel special-builtin, stop failure, reload failure; verified
under busybox ash), `deploy.sh`'s 0600 `rootchan.host`, `uninstall.sh`'s missing
app-label prelude, `server.py`'s `.pyc`/`__pycache__` leak, unbounded HTTP
request, evictable live beacon token, dangling `tv_sock` and stale RPC waiter,
the Python lane's missing sane-cred gate, the cred-scan desync/budget and the
`smack_relabel` PA/VA mix. **Residual, deliberately not changed:** the peer
tokens are self-service (a host that can reach port 80 can fetch a token; the
LAN is the boundary - `SECURITY.md` now says so); ~~`mask.sh` and the payload
list units without `--full`~~ (fixed 2026-11-01 in `mask.sh` and 2026-11-02 in
the payload, v47 - `test_constants.py` asserts the flag in both); ~~`mask.sh`
counts a failed stop but not a listed unit that stays `active` while its stop
returned 0~~ (fixed 2026-11-01, re-verified live on the TV 2026-11-03 -
`CHANGELOG.md`); `HEAD` answers with a body and `OPTIONS` is served as `GET`
(**pinned 2026-11-03**, behaviour unchanged: two checks in
`tools/test_server_unit.py` assert both lanes so an accidental change shows as
a visible test diff).

1. **~~Deploy v41 / cold boot / kill -9 / uninstall + recover~~ — all done 2026-10-27.**
   Restart-rooted in ~1 s; token live; cold boots 36 s and 49 s; `kill -9` back in
   ~2 s; uninstall restored stock and stayed unrooted through a cold boot;
   `recover.sh` with the PC URL reinstalled v41 and that boot row fired on the next
   cold boot. The run also fixed two `recover.sh` bugs (rendered-guard marker grep,
   Tizen UEB unsigned-file refusal) and added `auto_root --script-args`.
2. **~~High-half read mechanism~~ — RESOLVED 2026-11-03: DMA-window theory refuted,
   the memory map is measured.** Passive reads (`/proc/iomem`, `/proc/cmdline`,
   `/proc/zoneinfo`, `/proc/meminfo`, DT `memory/reg` + `reserved-memory`)
   over 31337, then deliberate **read-only** high-PA reads through the browser
   stub (video30 — the stub's node; an earlier draft of this record said
   video40). Findings:
   - System RAM is 0x20000000-0x697fffff + 0x87000000-0xadffffff
     (`sdp_sparsemem`, `vmalloc=400M`); `high_memory` VA `0xF0400000` confirmed.
   - **A 156 MiB no-map carve-out (DT reserved@0-4) sits at PA
     0x40000000-0x49C00000, inside the lowmem span** — cross-checked exact:
     zoneinfo Normal spanned-present = 39,936 pages = the carve-out; HighMem
     spanned-present = 724 MiB = the 472 MiB inter-bank gap
     (0x69800000-0x87000000, reserved@5/6/7/9) + a 252 MiB reserved@10-19
     tile (0x87000000-0x96C00000). So VA 0xE0000000 is the carve-out EDGE,
     not "inside readable lowmem", and the old "video40 DMA window (~512 MiB)"
     suspect is **refuted**.
   - Deliberate reads: the carve band reads fine but holds device content
     (no task allocates there — which is why every beaconed high pointer,
     PA 0x4083d000-0x448b8000, was unreadable); `0x46000000` itself reads,
     `0x46100000` HANGS (the historical boundary is precise: base of DT
     reserved@3); **the top 104 MiB of the linear map (PA
     0x49C00000-0x50400000) reads fine through video30** — new fact. The
     repo's 0x40000000 sweep cap is exactly the first absent frame — proven
     optimal, unchanged. One stub wedged at 0x46100000 as expected, cleared
     with `RSET`; no reboot needed at the time — but past-0x46000000 reads
     are potentially system-fatal with delayed effect (the wedged renderer
     stayed blocked in the driver and the TV auto-rebooted hours later),
     so kill the wedged renderer promptly (RSET + page reload).
   - **Verdict re-read corrections:** the 3 pre-v43 `high-scan` lines predate
     per-run tags entirely (genuine misses of the then-constant tag, not the
     v44 `hit+8` bug); all 9 post-v44 high parents translated into the carve
     band with `pc=0`; misses are ±16 MiB-band-limited (five budget-limited;
     one full-band sweep at ms=829 with 0 hits — a bounded miss, not evidence
     of absence); `cred-elsewhere` lines are not high-half evidence.
   No boot-path change: a high task/cred value is still a garbage read and
   attempt 2 remains the floor. Dated entry: `CHANGELOG.md` 2026-11-03.
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
5. **Debloat — durable; service suppression is live.**
   **73 apps are durably disabled** (`pkgcmd --global`: tier 1 10, tier 2a 5,
   voice 22, batch 2 29, batch 4 game trio 3, batch 5 leftovers 3, batch 6
   utterance core 1) and **29 units / 23 binaries** are on the mask list,
   re-applied at every boot by the payload from
   `/opt/usr/data/debloat-masks.txt`. Batch 4 cold-boot passed 2026-11-05
   12:31 (69 rows); batches 5 and 6 cold-boot passed 12:59 (73 rows;
   `masks=29 stopped=29 killed=3 fail=0 missing=0 activating=2
   listed-activating=0 loop-check=ok`; `tv_health` 16/16).
   Two ids are **not** disabled and never will be, both phone-confirmed:
   `com.samsung.tizen.samsung-analytics` (the SES privilege provider
   `smartthings-client` requests) and `org.tizen.easysetup-daemon` (disabling
   it alone flips SmartThings from online to offline). The 16 sharing ids stay
   reverted (prudence, not the cause).
   Remaining: the 17 tier-2b ids need the Control Center layer or owner
   decisions; `org.tizen.tv.tagpro-service-tv.service` is **deferred**
   (2026-11-05); `bluetooth-monitor.service` is excluded by the owner;
   HbbTV/Cobalt/AI Sound are non-removable. Design:
   `debloat/models/qnx1d/v42-design-brief.md`; the two policy files are
   installed by `deploy.sh` and deleted by `uninstall.sh` — that is the
   revert. Full history and per-batch detail: `debloat/AGENTS.md`.
6. **Reference-derived follow-ups, in value order:** ~~a per-run task tag
   (`PHYSRPT`+pid) plus a pid/tgid and `real_cred == cred` check~~ - **DONE in
   v43 (2026-10-30)**: per-run `PHYSRPT`/`PHYRFORK` tags, the pid/tgid accept
   rule with refusal of a readable-but-different pid, and `SameCredPair` on
   every task-based patch. **v44 (2026-10-31) closed two holes the review found
   in that rule:** the pid read is tri-state (a readable pid of ZERO - the
   freed-task shape - was folded into "unreadable" and fell through to the
   parent-uid latch; only a real read failure does that now), and accepts are
   **ranked** (exact tag > pid > prefix, for `self` too) so a weaker accept
   later in the prev-chain cannot overwrite an exact one. `stale=` is per-poll
   and `tag=none` means the v23 `maybe` latch. Locked by `test_constants` +
   the `sim_rpc` v43/v44 tests.
   The remaining follow-ups here are:  **OTA hardening: the mask half is DONE
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
8. **FIXED in v48 (deployed 2026-11-04; cold boot passed 22:11): the payload's counter
   writes are read back and a failure is beaconed — the 2026-11-04 failure
   mode cannot recur silently.** (History: the failure was demonstrated live,
   and the live failure was the diagnostic's own artifact.) The degraded long-mode process beaconed `long-exit attempt=5
   count=1`, but its post-exit relaunch beaconed `attempt=5` again instead of
   `attempt=6`: that process's `.dsh_try` write-back had failed silently.
   Cause: the diagnostic planted the counter over the root channel (`echo 4
   > /tmp/.dsh_try` as root), leaving a root-owned file in sticky `/tmp`,
   while the payload updates the counter at start as uid 5001 — the write
   throws and `catch { }` hides it. Corroboration: all four forced starts
   read the unchanged root-owned `4` (pids 19275/19667/20072/20806 all
   beaconed `attempt=5`); `.dsh_long` was created by the payload itself and
   is owned by `owner` (live `ls`), which is why its write persisted; and
   the same log holds the control case — deploy.sh removes the counter as
   root, attempt 1 creates it as uid 5001, attempt 2 updates it (roll 6: pid
   18227 wrote `1`, pid 19110 read `1` and beaconed `attempt=2`). A normal
   boot therefore has no counter defect: attempt 1 creates `.dsh_try` itself
   and later attempts update it. **v48 (deployed 2026-11-04; cold boot passed 22:11)**
   closes the gap: both counters go through `WriteCounter` (write, read back,
   `counter-write-failed file=<name> want=<n> got=<...>` beacon, never a silent
   retry). A failed `.dsh_try` write forces long mode, so the fast-exit budget
   cannot loop; a failed `.dsh_long` write suppresses the exit (`long-exit
   suppressed (counter write failed)`) and falls through to the idle, so the
   3-exit cap cannot be disarmed. Cold boot passed 2026-11-04 22:11:
   `masks=29 stopped=29 killed=4 fail=0 missing=0 listed-activating=0
   loop-check=ok`, `tv_health` 16/16, zero `counter-write-failed` lines.

## New falsifiable checks — from the tizen-tv-control-center cross-reference — both SETTLED 2026-11-03

An independent S90D project (EU, **T-PTMxxxx** — the same firmware family as
this unit) runs root commands **over SDB** with Developer Mode enabled, and
replaces `/opt/etc/parseinfo.sh` wholesale as its persistence boot hook. Both
conflicted with our recorded findings; both are now closed (details in
`FAILED.md` sdb/UEP sections and `CHANGELOG.md` 2026-11-03).

1. **~~SDB root-exec on our unit~~ — FALSIFIED 2026-11-03.** Developer Mode
   was found **already ON** live (`db/sdk/develop/mode=1`, the PC authorized),
   so `FAILED.md`'s "measured with Developer Mode OFF" premise was wrong and
   the 2026-10-20 recon probes re-ran under the S90D precondition directly:
   the service matrix is IDENTICAL — `shell:` whitelist-only, `sync:`/`tcp:`
   open, `root:` open but `root:on` → `Permission denied`, everything else
   closed. Developer Mode ON does not unlock sdb root on this unit. New
   mechanism knowledge: `develop/mode` gates CONNECTION AUTHORIZATION (a flip
   test: `mode=0` → TCP connect ok, CNXN handshake reset; `mode=1` →
   handshake completes), not the root capability — `sdbd_rootperm` stays
   unfilled. `sdbd_tcp.socket` only runs while the store app's
   `develop_mode` marker exists (ConditionPathExists drop-in), and
   `sdbd.service` runs as `User=sdk` with a limited capability set — sdbd is
   not root anyway, so even a successful `root:on` could not have produced a
   root shell. **Operational trap:** flipping `develop/mode` leaves both
   units FAILED and the port closed; `systemctl start sdbd_tcp.socket`
   restores it (all recorded in `FAILED.md`'s sdb section).
2. **~~`parseinfo.sh` as a second persistence hook~~ — ALREADY SETTLED;
   confirmed 2026-11-03 with no new experiment.** The proposed test was
   already run live on this TV on 2026-10-21 (private recon notes of that
   date): the consumer is `AT-HUB.service` (starter.target.wants,
   `ExecStart=/opt/etc/parseinfo.sh &` as root); an append test with backup
   was rejected at exec — `[uep][bash] the file is NOT signed!!`, the script
   did not run, its marker was never created, and the file was restored (md5
   `2c4ccd56e3f89818e9bafd6bef809262`). Today's verification: the live file
   is STILL md5 `2c4ccd56…` (805 B, 0777, root) and `/proc/target_version`
   carried the expected OSU string after that evening's boot — the
   unmodified script ran. UEP verifies script files at exec (direct and via
   interpreter), so the S90D wholesale-replacement approach cannot transfer
   to this unit. The test's `parseinfo.sh.bak` backup is still on the TV —
   harmless residue (recorded in `FAILED.md`).

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
- ~~**High-PA deliberate read:** one falsifiable check left from the
  memory-model work (`AGENTS.md` §11)~~ — **done 2026-11-03** (OPEN-ISSUES
  item 2: the carve-out is measured and the deliberate reads are recorded;
  the zoneinfo boundary was already measured).
- ~~**Encoding hardening beyond stdout:** TV-facing stdout already uses
  `errors="replace"` (a locale console used to crash the reporting tools on
  non-ASCII bytes), but a few tool file reads/writes still rely on the locale;
  pin `encoding="utf-8"` when touching them.~~ — **done 2026-11-03** for the
  one real TV-data read path: `tools/beacons.py`'s two `read_text` calls (the
  `--newest-start` read and the main grouping read) now pass
  `encoding="utf-8"` (the log is UTF-8; a cp1252 console could crash or mangle
  the read). A sweep found everything else already pinned or binary-mode;
  `test_logs.py`'s fixtures are ASCII written and read under the same locale
  on purpose and stay as-is.

## Closed history

The per-finding record of the 2026-10-23..26 review passes (P0/P1/P2 tables,
the five boot-tuning passes, environment notes) is archived in
[`docs/REVIEW-HISTORY.md`](REVIEW-HISTORY.md); dated narrative in
`CHANGELOG.md` (older passes: `docs/CHANGELOG-ARCHIVE.md`).
