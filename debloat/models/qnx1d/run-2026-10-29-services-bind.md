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

1. `mask.sh` MASK=1 over `services-units.txt` (now 23 units incl.
   `cis-api-service-app`): **23/23 masked, 0 failed.**
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
reboot gives stock behavior back. If it recurs during use, tcc's 30 s
loop (systemd-run + awk) holds it down; a future payload boot step could
do the same if it proves recurring.

**Diagnosis credit:** tizen-tv-control-center docs/06-picture-clarity.md
and docs/picture-fix-any-launcher.md (S90D, same firmware family).
