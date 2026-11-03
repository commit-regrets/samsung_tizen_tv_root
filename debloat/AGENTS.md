# AGENTS.md — samsung-tv-debloat handoff

Debloat lists and tooling for rooted Samsung Tizen TVs. Read this before
changing anything.

## The contract

Everything here runs against **a root shell speaking the 31337 line
protocol** (commands + newline, replies end with `__END__`), provided by the
samsung_tv_root toolkit. This repo never roots anything; it consumes root.
All TV reads/writes go through that channel (PC-side helpers:
`tools/root_shell.py`, `tools/run_root.py` in the toolkit repo).

## Current state (2026-10-30)

- QNX1D (2024 Neo QLED, Tizen 9, QTV T09): inventory harvested (446 packages
  from `/opt/dbspace/.pkgmgr_parser.db`), classified with Vetro 0.2.3+ rules.
  **Tiers 1+2a applied live 2026-10-29**: 20 packages durably disabled
  (11 tracking + 9 tcc-optional),
  ~25.9 MB of running ACR/ad processes freed. Run log:
  `models/qnx1d/run-2026-10-29-tier1.md`. Undo:
  `share/debloat-undo-global-20261029.sh` (live 2026-10-29 log; new apply.sh
  writes undo under `/opt/usr/data/` and plants the two systemd sentinels
  itself — replay with `cat file | sh`).
- **Disable store found:** `pkgcmd -D -t app -n <id> --global` writes
  `package_app_info.app_disable='true'` in `/opt/dbspace/.pkgmgr_parser.db`
  and the launcher then reports "not available". `--uid` (what tier 1 used
  first) returns ok and writes nothing. **Cold-boot readback CONFIRMED
  2026-10-30 for ALL 20 rows** (mains cycle: `id -u` = 0, count = 20, both
  canalysis/pisa sentinels still present) - the store is durable as-is, no
  payload change needed for it.
- **Services layer: 29 units masked, and now durable (v42).**
  `lists/services-units.txt` holds 29 units; the boot payload re-applies all of
  them from the root-owned `/opt/usr/data/debloat-masks.txt` at every boot
  (`deploy.sh` installs that file; deleting it is the revert). **Cold-boot
  acceptance PASSED 2026-10-30 14:05:40** (mains cycle, no PC involved):
  `masks=24 stopped=24 killed=3 fail=0 missing=0 listed-activating=0
  loop-check=ok newhome=set(0),loop-started`, and live afterwards **24/24
  masked-runtime with none active** (18 inactive + 6 failed) and zero processes
  under the listed binaries.  That run used the **24-unit list**; it was then extended to 34 with the OTA
  stack and later cut to **29** when the four phone-path units and the
  `org.tizen.easysetup-daemon.service` mask were dropped (2026-10-30
  evening, SmartThings). **First 29-unit boot PASSED 2026-10-30 19:29:41**:
  masks begin n=29, masks=29 stopped=29 killed=4 fail=0 missing=0
  activating=1 listed-activating=0 loop-check=ok newhome=set(0),loop-started,
  and the easysetup unit now starts at boot (NRestarts=0).
  **Second 29-unit boot under v44 PASSED 2026-11-01 14:23:02**: rooted on
  attempt 3 at t=38 s, then `masks=29 stopped=29 killed=5 fail=0 missing=0
  activating=3 listed-activating=0 loop-check=ok newhome=set(0),loop-started`
  at t=45 s; live after it 37 app rows, 29 masks (+3 vendor `.done` markers in
  `/run/systemd/system`), `easysetup-daemon` active with NRestarts=0.
  **Extended to 34 on 2026-10-30 14:50** with the OTA / firmware-update stack:
  `vdsystem-update-manager.{service,timer}`, `was-background-update.{service,path}`,
  `swu-verifier-tv.{service,timer}`, `swu-core-tv.service`,
  `swu-service.service`, `vdca-update.service`, `swu-auto-upgrade.timer`
  (+2 kill-list binaries). Re-run beaconed `masks=34 stopped=34 killed=1 fail=0
  missing=0 activating=0 listed-activating=0 loop-check=ok
  newhome=set(0),loop-active` — and **`vdsystem-update-manager.service` was a
  SECOND restart loop** (`Restart=always`, `ExecMainStatus=0`,
  `activating (auto-restart)`), which is why the global count fell 2 -> 0. The
  dependency gate passed (only `swu-core-tv`/`swu-service` `Requisite=` and
  `swu-factory-usb-upgrade.target` `Requires=` the verifier — all disabled; they
  simply cannot start, which is the intent). **Rejected lever:** the vendor's own
  OTA switch is `ConditionPathExists=!/mnt/backup/OS_UPGRADE_FLAG`, but
  `/mnt/backup` is a symlink to `/mnt/systemrw` (trap 9) — do not plant it.
  **History — do not read it as the current state:** round 4 (2026-10-29)
  masked 23/23 live (0 respawn in the 8 s check, ~192 MB sum-RSS upper bound
  across the 21 running `/usr/bin` services); the 24th,
  `org.tizen.easysetup-daemon.service`, was added 2026-10-30 after the
  restart-loop detector found it spinning at `NRestarts=654` (at the time
  its app was disabled in tier 2a and `Restart=on-failure` retried forever;
  **both that row and this unit mask were removed on 2026-10-30 evening -
  either one kills SmartThings phone status**); at **12:35
  that day only that one mask was up**, because `/run` masks die with the
  reboot — the session-only design v42 removed. Tooling (still the
  human-facing path): `tools/mask.sh` (masks, reload, stop, refusal test, kill
  pass, picture guard with the persistent `newhome-fix` 30 s loop,
  restart-loop check; idempotent) and `tools/unmask.sh`.
  **Batch 3 REALITY (2026-10-30): 22 voice ids, sharing reverted.** The first
  run disabled 38 ids (voice 22 + sharing 16) and **SmartThings phone control
  stopped working**.  **Cause (owner-confirmed bisect, one variable at a time,
  the same evening): `org.tizen.easysetup-daemon`.**  Disabling it alone flips
  SmartThings from online to offline; its manifest carries the IoT
  master/resource metadata that `smartthings-thing` also provides, and the
  client keeps running with cloud sockets up while the phone shows offline.
  It is **denylisted**, dropped from tier 2a, and **its unit is off the mask
  list** (masking the unit stops the same daemon) - 24-unit list -> 29 units.
  `com.samsung.tizen.samsung-analytics` is denylisted too, but for a different
  reason: the client's `tizen-manifest` requests its appdefined privilege, so
  disabling it leaves the client up with the phone offline.  It was the first
  suspect and **is not sufficient** - re-enabling it did not restore the phone
  (18:2x), which is what forced the row-by-row bisect that found easysetup.
  The sharing-batch revert was a wrong guess from reading `referencedBy`
  backwards (`multiscreen` uses the client, not the reverse) - the 16 stay
  re-enabled as prudence.  The five SmartThings-stack ids are denylisted and
  dropped from tier 2a (9 -> 5).  Standing set: **66 app rows** (tier 1 10 +
  tier 2a 5 + voice 22 + batch 2 29) and **29 units / 23 binaries** (`pushd` /
  `register-device` / `p2p-asm` unmasked: phone-path, ~1.5 MB).
  **Batch 2 (commercial/hotel/factory) applied 2026-11-01 21:38**
  (`lists/batch2-commercial.txt`, 29 ids: `disabled=29 failed=0 of 29`,
  readback 66 rows, 0 activating, undo log
  `/opt/usr/data/debloat-undo-20261101-213858.sh`).  It is the planned 30 of
  33 minus `com.samsung.ep.hotel.uigadgets`, which has no app row in
  `package_app_info` here (`pkgcmd -D` would fail); the three coupled ids
  stay out.  ~0 MB (hotel/factory code does not run at idle), so the gain is
  storage and attack surface.  **Cold boot PASSED 2026-11-01 21:54** (mains
  cycle): 66 rows persisted, `masks=29 stopped=29 killed=3 fail=0 missing=0
  activating=7 listed-activating=0 loop-check=ok` at t=40 s.  Live leftover:
  `/usr/bin/rscmgr-service` (pid 619, Remote Shop Care) is a **service, not
  an app** - the app disable does not touch it; it is a q3deps-gated
  follow-up, not part of batch 2.
  **Lesson:** `referencedBy` = who uses the package.  A package that a
  keep-side app USES is a risk to that app; a package that USES a keep-side
  app is not.  And check the keep-side app's own `tizen-manifest.xml`
  privileges (that is how analytics was caught - it was a real dependency,
  just not this outage's cause).
  **Rule:** every mask-list addition needs the q3deps gate run *before* the
  add (the multiscreen entry went in without one; it was removed again).
  **Rule: the decision ledger is `registry.tsv`** (2026-11-01) - one row per
  id with `status` (applied / deferred / never / reverted / rejected), reason,
  evidence, date and owner.  The list files stay the apply/undo input and
  `apply.sh` keeps its runtime DENY, but every decision must also have a row:
  `tools/test_debloat.py` asserts all three agree (applied == the four lists,
  deferred == tier2b, DENY ⊆ never, reverted recorded, no id twice).  Before
  this existed the same fact lived in 3+ files and drifted twice in one day
  (tier2b claimed two applied ids were deferred; the README said 24/24 when
  the lists held 29/23).
  **Open:** tier 2b needs the Control Center layer; batch 2 is applied and
  cold-boot verified (2026-11-01); batch 3 is
  voice-only and done; **tcc's five extra service candidates are
  EVALUATED AND REJECTED (2026-10-30)**: measured live, their sum-RSS (~35.5 MB)
  is ~10x the real cost - PSS is 1.77 (slive-provider-daemon) + 1.01
  (screen_sharing) + 0.49 (user-presence) + 0.08 (wifi_state_manager via
  `wsm-service.service`) = **~3.4 MB total**, and `mcf-agent-service` is an *app*
  (`app_launcher -s com.samsung.tizen.mcf-agent`) that was inactive. The Wi-Fi
  state daemon is not something to touch while the root channel depends on the
  network. Do not re-propose these without a PSS number; the four former "unit-less" holdouts
  are resolved and on the mask list (TIFADaemon_L <- automation-service,
  TIFSDaemon <- factory-service, SCSAgent <- scs-agent.service,
  SWUAutoUpgrade <- swu-auto-upgrade.service); `cis-api-service-app` churn
  stops in masked sessions (its unit is on the list); SWUCoreTV/SWUService/
  SWUVerifierTV are on the list via their own units now
  (`swu-core-tv.service`, `swu-service.service`, `swu-verifier-tv.service`) -
  corrected 2026-10-30: they are no longer 'launchpad with no unit'. `bluetooth-monitor.service` is **excluded, not a candidate**:
  it is the boot-time Bluetooth re-activator (unit comment: "check previous
  BT-connection status and re-activate BT when boot"; wanted by
  `starter.target` + `swu-standalone.target`; `bt-monitor` holds
  `/dev/micom-msg` and `/dev/eeprom`; `Restart=on-abnormal`, 2 s). It is
  excluded on the owner's instruction (Bluetooth must keep working): tcc
  blocks it and reports the remote still works, but that is unverified on
  this set, so it stays out of the mask list AND out of the kill list
  (`services-bind.txt`) — ~5.8 MB is not worth the experiment.
- Idle-RSS upper bounds (pre-run baseline): see
  `models/qnx1d/resource-math.md` — sum-of-RSS upper bounds, not freed
  pages. The measured result is the per-process A/B diff in the run logs
  (the same dump re-taken after an apply, attributed per process).

## Discipline (each item earned somewhere)

1. Dry run first: every list is applied with `APPLY=0` before the real run.
   The dry run is a gate: it exits non-zero on a refused entry, and every
   script exits 2 when the list yields no valid ids (a "0 of 0" success is
   how the old stdin fallback hid doing nothing).
2. Real runs print one result line per package (a batch list is fine) and
   stop at the first unexpected failure; the undo line is recorded before
   each disable.
3. Readback oracle is the **process table** (`/proc/<pid>/exe`, attributed
   per package) plus `package_app_info.app_disable` after a `--global`
   disable. `--uid` writes no row. `aulctl is-active` does not know svcapps,
   and busybox `ps` shows only ~228 of ~408 processes.
4. Never disable: the carrier app (`MultiControl-Service`), the Smart Hub
   dependency (`coba.adagent`), the privacy-choice UIs, Home (`org.tizen.menu`,
   `com.samsung.tv.home.sidebar`), DRM (`unified-drm-*`),
   `com.samsung.tv.screen-analysis-dbmgr` (tcc measured picture-processing
   breakage), **the SmartThings stack** (`smartthings-client`,
   `smartthings-thing`, `smartthingsfind-daemon`, `mde-framework`,
   `tvsensor-iot-service`), **`com.samsung.tizen.samsung-analytics`**
   (the client's SES privilege provider) and **`org.tizen.easysetup-daemon`**
   (phone-confirmed 2026-10-30: this one disable flips SmartThings from
   online to offline; do not mask its unit either), Bluetooth (`bluetooth-monitor.service` / `bt-monitor`):
   **excluded on the owner's instruction** — it is the boot-time BT
   re-activator (holds `/dev/micom-msg`, wanted by `starter.target`); tcc
   blocks it and reports the remote still works, but that is unverified on
   this set and ~5.8 MB is not worth the experiment. **Vetro itself** is
   never disabled either.
   App entries are hard-coded in `tools/apply.sh`; service entries are kept
   out of both `lists/services-units.txt` and `lists/services-bind.txt`.
5. Disable only; uninstall is out of scope (irreversible on
   preloaded/system packages).
6. Lists are validated bare app_ids only — nothing else reaches a command
   (injection safety, cleanyourtv #165).
7. After any apply: channel health (`id -u` = 0), beacon check, and a reboot
   with the channel returning on its own.
8. Measure, then claim: RAM numbers are sum-RSS upper bounds; only an A/B
   dump diff is a result.
9. **UEP blocks `sh /tmp/script.sh`** on the TV (unsigned file) — the working
   form is `cat /tmp/script.sh | sh -s <list>` (same as `FAILED.md`).
   Because the script itself arrives on stdin in that form, the list is
   always a **file argument**: a piped list is refused (exit 2), never
   silently read as empty. Fetch script and list with `curl -o` first.
10. **`pkgcmd -D` does not kill running instances and `pkgcmd -k` is a no-op
   on this firmware** — after disabling, kill the processes by
   `/opt/usr/apps/<pkg>/` exe path (root), then expect a respawn war:
   `launchpad-process-pool` and systemd units relaunch services. Identify
   units with `systemctl status <pid>` and stop them (`adagent-service`
   hid behind pisa). One-shot `/bin/true` bind-mounts pin launchpad-held
   binaries.
11. **`--uid` disables do not survive a reboot** (mains cycle 2026-10-29:
   all 11 were back). **`--global` does write a durable store — cold-boot
   verified 2026-10-29 (all 11 rows survived a mains cycle):**
   `/opt/dbspace/.pkgmgr_parser.db` `package_app_info.app_disable`. The
   user DB and `package_app_info_for_uid` stay empty. A repeat `--global`
   exits 25 with "Failed to get appinfo" while the row stays true — that
   error is the already-disabled path, not proof that `--global` is
   unsupported. Launcher honors the row (`app_launcher -r` → not available).
   Units that ExecStart the binary ignore it. canalysis and pisa ship
   `ConditionPathExists=!/opt/usr/share/systemd/system/<sentinel>`; an empty
   file there blocks the start and lives on `/opt`. `/etc` is read-only, so
   `systemctl mask` cannot persist. Cold-boot readback done 2026-10-29:
   all 11 `--global` rows and both sentinels SURVIVED the reboot - the
   `--global` store and the two vendor sentinels are durable as-is, and v42
   does NOT need to re-assert app disables. v42's only job is the /run mask
   re-assertion for the 29 service units (see rule 13 and
   `models/qnx1d/v42-design-brief.md` for the reviewed design).
12. busybox `ps` shows only ~228 of ~408 processes; idle meminfo deltas are
   dominated by TV activity. Attribute per-process from `/proc` and compare
   per-package, never by global counters alone.
13. **Service suppression: `/run` masks work, everything else doesn't.**
   (2026-10-29 forensics: empty files and /dev/null symlinks under
   `/opt/usr/share/systemd/system` are inert and drop-ins there never load -
   `/opt` is NOT in systemd's UnitPath; runtime bind-mounts of `/usr/bin`
   are bypassed by the respawner, 19/25 came back. What works:
   `ln -sf /dev/null /run/systemd/system/<unit>` + daemon-reload ->
   `is-enabled` = masked-runtime, start refused, 13/13 held.) `/run` masks
   are session-only (tmpfs) — durable suppression = the boot payload
   re-writes them each boot (v42). The 21 services held ~192 MB sum-RSS at
   idle — the biggest remaining debloat prize. Binary name != unit name:
   map with `systemctl status <pid>` (TIFADaemon_L <- automation-service,
   TIFSDaemon <- factory-service, SCSAgent <- scs-agent.service,
   SWUAutoUpgrade <- swu-auto-upgrade.service — all on the mask list);
   SWUCoreTV/SWUService/SWUVerifierTV have units after all (2026-10-30) and
   are masked like the rest; verify masks by `is-enabled`, and
   never by mount listings or `/opt` file existence.
14. **Two traps earned from tizen-tv-control-center (2026-10-30):**
   (a) **A disabled app leaves a restart-looping unit.** `pkgcmd -D` stops the
   app but its unit's `ExecStart=app_launcher -s <app>` fails forever with
   `Restart=on-failure` — `org.tizen.easysetup-daemon.service` had
   `NRestarts=654` (5 s cycle) and nobody noticed. So *every* app disable
   needs a unit check (`systemctl show <unit> -p NRestarts -p ActiveState`),
   and `mask.sh` now fails if a listed unit is still `activating`.
   The 2026-11-01 hardening reads the state instead of the exit code (only
   `inactive`/`failed` accepted, and pass 5 fails a listed unit that is
   `active` in the dump too); **re-verified live 2026-11-03** on a freshly
   mains-cold-booted v47 set (boot rooted t=37 s): `already=29 stopped=29
   fail=0 killed=1 reload_ok=1 loop-check=ok activating=0 listed-activating=0
   listed-running=0 newhome=active` - the is-active parsing found no listed
   unit active/activating after the stop pass, and the kill pass removed one
   leftover `p2p-asm-UI` process (record: `CHANGELOG.md` 2026-11-03).
   (b) **The avocd `new_home` flag can be re-set mid-session**, not only at
   the moment of masking, so a one-shot SetNewHome is not enough: `mask.sh`
   installs the persistent `newhome-fix` 30 s loop (`systemctl stop
   newhome-fix` to remove it; it is transient and dies at reboot).
   **Readback semantics:** `CheckAutoMotionPlus` = 1 means picture settings
   are available; **0 is expected while Samsung Home is in front** (Home
   keeps motion processing off), so verify the fix with an app/video on
   screen, not on the Home screen. A transient unit's dbus access works
   (measured rc=0), and the loop is what keeps the flag clear once Home
   hides.

## Model data

`models/qnx1d/`: qnx1d-inventory.json (per-package: flags, area, role, purpose,
referencedBy), disable-plan.md (batches + apply protocol), optional-menu.md
(160 optional packages for owner selection), resource-math.md.

## Attribution

Vetro 0.2.3 catalog rules (MIT) - see `third_party/vetro/LICENSE`. List-file
discipline inspired by cleanyourtv.
