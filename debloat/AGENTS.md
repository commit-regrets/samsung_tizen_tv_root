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
- **Services layer: 34/34 units masked, and now durable (v42).**
  `lists/services-units.txt` holds 34 units; the boot payload re-applies all of
  them from the root-owned `/opt/usr/data/debloat-masks.txt` at every boot
  (`deploy.sh` installs that file; deleting it is the revert). **Cold-boot
  acceptance PASSED 2026-10-30 14:05:40** (mains cycle, no PC involved):
  `masks=24 stopped=24 killed=3 fail=0 missing=0 listed-activating=0
  loop-check=ok newhome=set(0),loop-started`, and live afterwards **24/24
  masked-runtime with none active** (18 inactive + 6 failed) and zero processes
  under the listed binaries.  That run used the **24-unit list**; the current
  standing state is the 34-unit list below (the extension, not a regression).
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
  restart-loop detector found it spinning at `NRestarts=654` (its app is
  disabled in tier 2a and `Restart=on-failure` retries forever); at **12:35
  that day only that one mask was up**, because `/run` masks die with the
  reboot — the session-only design v42 removed. Tooling (still the
  human-facing path): `tools/mask.sh` (masks, reload, stop, refusal test, kill
  pass, picture guard with the persistent `newhome-fix` 30 s loop,
  restart-loop check; idempotent) and `tools/unmask.sh`.
  **Open:** tier 2b needs the Control Center
  layer; batch 3 awaits owner picks; the four former "unit-less" holdouts
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
   breakage), Bluetooth (`bluetooth-monitor.service` / `bt-monitor`):
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
   re-assertion for the 34 service units (see rule 13 and
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
