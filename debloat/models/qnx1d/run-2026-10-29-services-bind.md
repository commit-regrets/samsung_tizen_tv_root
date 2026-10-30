# Services bind-mount experiment — 2026-10-29 (live, QNX1D)

**Result: runtime bind-mount + kill did NOT suppress the services.**
19/25 respawned running the original binary within the ~4 minute soak.
The measured prize (192 MB sum-RSS across 21 running services) requires
boot-time overlaying (tcc's ordering) — a v42 payload feature.

## What was done
1. `bindapply.sh` dry run: 25/25 names validated.
2. Overlay: `mount --bind /bin/true /usr/bin/<name>` x25 — all succeeded.
   Content proof: `md5sum /usr/bin/data-service` == `/bin/true` while mounted.
3. Kill pass by exe path: **20 of the 25 services were RUNNING** at overlay
   time (~192 MB sum-RSS across 21 procs; 3 of 25 binaries absent on this unit).
4. ~4 min soak, then the standard dump, then `bindrestore.sh`: 25/25
   umounted, md5 back to original. TV state unchanged afterwards.

## Findings
1. **Runtime overlays do not hold.** After the kill, 19/25 services
   respawned running the ORIGINAL binary — forensically proven: the
   respawned `data-service` (pid 31037) had `/proc/pid/exe` md5 =
   original code while the on-disk path read `/bin/true`. The respawner
   (systemd units in private mount namespaces, or a Samsung supervisor
   exec'ing a different inode) bypasses the runtime mount. tcc does not
   hit this because their overlay happens AT BOOT, before the services'
   namespaces/environments exist — ordering is the difference.
2. **The prize is real**: the 21 running services held ~192 MB sum-RSS at
   idle (top: data-service 19.1, contents-recognition-service 14.4 (ACR),
   nagsam-daemon 14.8, p2p-asm 12.8, SWUCoreTV 12.2, stability-monitor
   10.6, sp-kpi 16.0). If boot-time overlay suppresses them, that is the
   single biggest debloat win on the table — bigger than all app disables
   combined.
3. **3 of 25 binaries are absent** on this unit (fw-update-service,
   fw-update-init-download, SWUVerifierTV not found in baseline) — the
   list is still correct for this firmware family but is not a
   per-model guarantee (matches tcc's compatibility warnings).
4. **Verify overlays by content, not by mount listing**: this firmware's
   `/proc/mounts` and busybox `mount` did not list the bind mounts at all
   (grep count 0 while the overlay was provably active via md5). The
   tools already use rc-based reporting; content-md5 is the verification
   of record.
5. `MemAvailable` 442 -> 447 MB during the overlay: no signal (services
   kept running + idle variance) — consistent with finding 1.

## Next
- The boot-time overlay test requires the payload to apply the list before
  systemd starts the units — that is the v42 feature, now with a measured
  ~192 MB upper bound and a proven-on-S90D ordering (tcc).
- Interim state: nothing persistent changed by this experiment; the
  20 durable app disables from tiers 1+2a are unaffected.

## Round 2 — the working mechanism found: /run masks (2026-10-29 evening)

Three mask mechanisms were tried and the third works:

| Mechanism | Result |
|---|---|
| Empty file in `/opt/usr/share/systemd/system/<unit>` | **inert** — systemd's loader skips empty files |
| `/dev/null` symlink in the same `/opt` path | **inert** — `is-enabled` stayed `static` |
| Drop-in `foo.service.d/override.conf` with a false condition | **not loaded** — `/opt/...` is NOT in the UnitPath at all |
| **`/dev/null` symlink in `/run/systemd/system/<unit>`** | **WORKS** — `is-enabled` = `masked-runtime`, `systemctl start` refused ("Unit is masked"), service stays down |

The definitive evidence: `systemctl show -p UnitPath` = `/etc/systemd/system
/run/systemd/system /run/systemd/generator /usr/lib/systemd/system
/prd/usr/lib/systemd/system /run/systemd/generator.late` — `/opt` is not in
it, so the earlier `/opt` sentinel theory was wrong; the canalysis/pisa/
adagent blocks work because those two *vendor unit files* contain explicit
`ConditionPathExists` checks against those exact `/opt` paths (a Samsung
flag mechanism present in only a few units).

Round-2 run: 17/17 units masked via `/run`, refusal verified live
(`is-enabled` = masked-runtime; start refused), kill pass (19), 8-second
respawn check: **13/13 unit-backed services stayed down**. The 4 that
respawned (`SCSAgent`, `TIFADaemon_L`, `TIFSDaemon`, `SWUAutoUpgrade`) have
**no systemd units** — the app framework launches them directly
(~28.7 MB combined per baseline; parent forensics next session).

## Standing state & persistence
- The masks are **session-only by design** (/run is tmpfs): they suppress
  the services until the next reboot, then self-clean. Left in place
  tonight for live evaluation.
- Durable service suppression therefore still needs the boot payload
  (v42): at each boot, write the same `/run` masks + daemon-reload + stop/
  kill — simpler and cleaner than bind-mounts (pure systemd, no namespace
  games). The round-1 finding stands for bind-mounts specifically; the
  payload route uses masks instead.
- Tools updated to the working mechanism: `tools/mask.sh` / `unmask.sh`
  now write `/run` symlinks; `lists/services-units.txt` holds the 17 unit
  names (+ notes on the 8 binaries without units).

## Revised resource picture
- Tier 1+2a app disables (durable): ~26 MB running processes freed.
- Services layer (session tool today, v42 for durable): ~192 MB sum-RSS at
  idle across 21-22 procs, of which the mask suppresses 13 units; the 4
  unit-less daemons (~29 MB) need separate handling.

## Round 3 — the ~35 MB holdouts suppressed (2026-10-29 evening)

The five non-tier services (SCSAgent, TIFADaemon_L, TIFSDaemon,
SWUAutoUpgrade, emergencyLogTransmitter; ~35 MB sum-RSS) turned out to be
unit-backed after all — with unit names unrelated to their binary names,
resolved via `systemctl status <pid>`:

    TIFADaemon_L  <- org.tizen.tv.automation-service.service (static)
    TIFSDaemon    <- org.tizen.tv.factory-service.service (disabled preset, running anyway)
    SCSAgent      <- scs-agent.service (enabled)
    SWUAutoUpgrade<- swu-auto-upgrade.service (disabled preset, running anyway)
    emergencyLogTransmitter <- emergency-log-transmitter.service (disabled, + bootseq wants symlinks)

All five /run-masked (`is-enabled` = masked), `systemctl start` refused on
every one, processes stopped and verified gone after 10 s (remain=0).

**The ~35 MB holdout set is fully suppressed.** Session totals now:
20 app disables (durable) + 22 unit masks + 2 vendor-condition sentinels =
the entire telemetry/ACR/ads/services stack down, ~218 MB sum-RSS
suppressed, ~35 MB of it identified in this round.

Lesson added to the set: **binary name != unit name.** The reliable mapping
method is `systemctl status <pid>` per process, not name matching.

## Round 4 — full re-assert run after cold boot (2026-10-29 22:0x UTC)

Post-mains-cycle state: /run masks gone (tmpfs), all services back. This
run re-applied the complete layer and validated the v42 shape end to end
by hand:

1. `mask.sh` MASK=1 over `services-units.txt` (then 23 units incl.
   `cis-api-service-app`): **23/23 masked, 0 failed.**
   (2026-10-30: `bluetooth-monitor.service` was briefly added and then
   demoted to a commented candidate — never masked live; the committed list
   is 23, the same 23 measured here.)
2. Kill pass over `services-bind.txt`: **19 processes killed** (the
   services had all restarted after the reboot, as expected).
3. 8 s respawn check: **alive_after8s = 0.** First time the ENTIRE
   telemetry/ACR/ads/service stack was verified down, including the four
   previously-unsuppressible holdouts (their parent units are now
   identified and masked).
4. Q3 reverse-dependency gate PASSED (5 hard couplings, documented in the
   brief; one real feature loss: DLNA casting via vd_dmr depends on
   register-device).

**This manual sequence IS the v42 payload step.** The payload change is:
run this exact sequence after SUCCESS-R00T on a background thread, from a
mask list shipped on /opt.

## Round 5 — picture settings greyed out: avocd `new_home` flag (2026-10-29 late)

**Symptom (owner report):** Brightness and Picture Mode no longer available
after the suppression session.

**Cause (not the disable list itself):** the AV-output daemon `avocd` keeps
a `new_home` flag — Samsung Home sets it to 1 while its UI is on screen
(motion processing off behind the home screen) and back to 0 when it hides.
With the flag stuck at 1, Picture Clarity / Picture Mode / Brightness are
greyed out. tcc documented this for home-screen replacement and
**explicitly ruled out the debloat as the cause** — our aggressive kill
pass likely raced Samsung Home's flag reset, leaving it at 1.

**Fix (one command, applied live, verified):**

```sh
dbus-send --system --print-reply --dest=org.tizen.tv.avoc /org/tizen/tv/avoc   org.tizen.tv.avoc.AvOutputControl.SetNewHome int32:0
```

Readback check (`int32 1` = available, `int32 0` = greyed out):

```sh
dbus-send --system --print-reply --dest=org.tizen.tv.avoc /org/tizen/tv/avoc   org.tizen.tv.avoc.AvOutputControl.CheckAutoMotionPlus
```

Verified: 0 -> fix -> 1, still 1 after 40 s. The flag is memory-only; a
reboot gives stock behavior back. **Adopted 2026-10-30:** tcc's 30 s loop
is now installed automatically by `mask.sh` (transient unit `newhome-fix`,
`systemd-run` + awk; `systemctl stop newhome-fix` removes it), because the
flag can be re-set mid-session and a one-shot at boot is not enough. The
v42 payload step does the same.

**Diagnosis credit:** tizen-tv-control-center docs/06-picture-clarity.md
and docs/picture-fix-any-launcher.md (S90D, same firmware family).

## Round 6 — the loop detector's first catch, and the picture loop (2026-10-30)

The two tcc lessons folded into the tooling before v42 was written:

1. **Restart-loop check.** `mask.sh` now reads
   `systemctl list-units --all --no-legend --plain` once and fails the run if
   any *listed* unit is `activating` (the global count is reported for
   context; an idle boot here already has 2, so the global number is not the
   signal). First live run of the check: `org.tizen.easysetup-daemon.service`
   was in `activating (auto-restart)` with **`NRestarts=654`** and climbing
   (~5 s cycle) — the tier-2a app disable leaves `app_launcher -s
   org.tizen.easysetup-daemon` failing forever under `Restart=on-failure`.
   No unit `Requires=`/`Wants=`/`BindsTo=` it (checked live), so the unit was
   added to `lists/services-units.txt` (24th entry) — the completion of an
   app disable, not a new decision. Every other `app_launcher` unit of a
   disabled app reads `NRestarts=0`.
2. **Persistent picture loop.** `mask.sh` keeps the immediate
   `SetNewHome int32:0` + verify and then starts the `newhome-fix` 30 s loop
   (idempotent: a second run reports `newhome=active`; `NEWHOME_LOOP=0` keeps
   the one-shot only).

The check is what makes v42's acceptance test meaningful: "0 respawn" was an
8 s process sample, this is a state read (and it found a loop that had been
running for 654 restarts).

Live verification of both fixes the same day (targeted, not a full session):

- Masked just `org.tizen.easysetup-daemon.service` (`ln -sf /dev/null` +
  `daemon-reload` + `stop`, the same sequence `mask.sh` runs): `is-enabled`
  = `masked-runtime`, `NRestarts` frozen (759 → 759 over 25 s; it had gone
  654 → 759 in the preceding ~20 min), state `failed` (it had already hit
  its start limit — **`failed` is stopped, not running**, so v42's check
  must accept `inactive` or `failed`, not only `inactive`), `is-active` exit 3.
- Started `newhome-fix` (`systemd-run`, the exact loop `mask.sh` installs):
  `is-active` = active, and the same command pushed through a throwaway
  transient unit returned `rc=0`, so dbus access from a systemd-run unit is
  not blocked by SMACK (the probe unit was `dbustest`, removed after).
- **Readback gotcha (record for v42):** `CheckAutoMotionPlus` read `0` right
  after `SetNewHome int32:0` even from the shell — because the set was
  sitting on the **Samsung Home screen**, where Home keeps motion processing
  off regardless of the flag. The 0→1 verification in round 5 was with
  content on screen. So "CheckAutoMotionPlus = 1" is only a valid acceptance
  signal with an app/video showing; at the Home screen `0` is correct and
  must not be read as a failed fix.

## Round 7 — bt-monitor: what it is, and why it stays excluded (2026-10-30)

The owner asked whether BT can be debloated too. Read-only forensics, then a
decision.

**Two separate units, not one.** `bluetooth-frwk-service.service` is the stack:
`ExecStart=/usr/bin/bt-service`, `DefaultDependencies=no`,
`WantedBy=sysinit.target`, active. `bluetooth-monitor.service` is the helper:
`/bin/fms_bt_monitor_launch.sh` → `/usr/bin/bt-monitor`, wanted by
`starter.target` + `swu-standalone.target`, `Restart=on-abnormal` 2 s. Blocking
the helper does not touch the stack.

**What the helper does.** Live inspection of pid 1896 (root, 4 threads,
194,832 B binary):

- strings: **`Powered` ×196**, `vconf` ×25, **`db/bluetooth/status`**,
  `PowerOn`/`power_on`, `bluetooth` ×9, `Adapter` ×55 — i.e. it reads the
  **saved BT state from vconf** and tracks the adapter's BlueZ `Powered`
  property over the system bus;
- fds: two AF_UNIX (dbus) sockets, `/dev/micom-msg` (rw, power/standby MCU),
  `/dev/eeprom` (**read-only**, module identity), `/dev/shm/shm_fms` +
  rwlock, the `/dev/log_*` set, `/dev/vlog`, `/dev/smart_deadlock`,
  `trace_marker`;
- `vconftool get -t string db/bluetooth/status` → **`1` (on)**;
- unit comment: "bt-service check previous BT-connection status and
  re-activate BT when boot".

So the split is: the stack brings Bluetooth up, and `bt-monitor` re-applies the
**last saved power state** to the adapter after a boot. With `status = 1`, that
means "turn BT back on after a power cycle" — which is how the BLE remote
reconnects by itself.

**Decision: excluded from both lists** (this was already the state; the reason
is now specific rather than "Bluetooth is scary"). The stack is independent and
stays untouched at runtime; the only thing forfeited is the boot-time restore,
and that is precisely the owner's input device. Gain would be ~5.8 MB (0.3 % of
RAM) against ~46 MB of other tcc candidates that do not touch the remote.

**If it is ever wanted, the only valid test is a boot test** (a runtime kill
proves nothing: `Restart=on-abnormal` respawns it in 2 s). That needs a durable
mask, so it can only happen after v42: put `bluetooth-monitor.service` in the
list for one boot, mains-cycle, check the remote reconnects, then remove it.
Recovery is self-cleaning (`/run` masks die at the next power cycle), but the
test boot may leave the set with no remote, so it needs the TV's own panel
button as the fallback path.

**Tooling note:** `dbus-send … org.freedesktop.DBus.ListNames` **hung twice**
(no reply within 30 s; the channel's 120 s kill recovered it). Do not use it
for diagnostics on this set — `/proc/<pid>/fd`, `grep -a` on the binary and
`vconftool` answered the same questions instantly.

