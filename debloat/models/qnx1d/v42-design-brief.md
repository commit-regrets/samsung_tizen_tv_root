# v42 design brief — durable service suppression: evaluate before building

**For:** an independent agent/human review BEFORE implementing anything.
**Question to answer:** is "payload re-asserts /run masks at boot" the best
design, or is there a better mechanism we missed?

## Environment

- Samsung QNX1D (2024 Neo QLED), firmware T-PTMxxxx family, Tizen 9, ARM32,
  kernel 5.4.249 (VMSPLIT_3G + HIGHMEM, SMACK enforcing, UEP active,
  `/usr` + `/etc` read-only, `/opt` writable, `/tmp` and `/run` are tmpfs).
- Root: uid 0 + full caps via the payload in `samsung_tv_root`
  (payload/Program.cs runs at every boot as an on-boot app; serves a line
  protocol on TCP 31337). Channel access from the PC:
  `cd C:\Users\Raghav\Documents\projects\samsung_tv_root`
  `python tools/root_shell.py "<command>" <TV_IP>`
  (env ROOT_SHELL_TIMEOUT=90; for scripts: `cat /tmp/x.sh | sh -s args` —
  UEP blocks `sh /tmp/file` but allows the pipe form.)

## Current state (2026-10-29, all verified live)

- **20 apps durably disabled** via `pkgcmd -D -t app -n <id> --global` →
  `package_app_info.app_disable='true'` in `/opt/dbspace/.pkgmgr_parser.db`.
  Cold-boot proven (mains cycle, readback). SOLVED — do not redo.
- **2 vendor-condition blocks**: `canalysis-service.service` and
  `pisa-service.service` (+ `adagent-service`) are suppressed by empty
  marker files `/opt/usr/share/systemd/system/canalysis-daemon` and
  `.../pisa-service` — those two vendor unit files contain
  `ConditionPathExists` checks against exactly those paths. Cold-boot
  proven. These two are done permanently.
- **23 systemd units** on `lists/services-units.txt` (session-only /run
  masks): the original 22 (17 from the `/usr/bin` binary mapping, incl.
  `pushd.socket`; 5 from `systemctl status <pid>`:
  `org.tizen.tv.automation-service.service` [spawns TIFADaemon_L],
  `org.tizen.tv.factory-service.service` [spawns TIFSDaemon],
  `scs-agent.service`, `swu-auto-upgrade.service`,
  `emergency-log-transmitter.service`) plus
  `com.samsung.tv.cis-api-service-app.service`. Round 4 live-masked all 23.
  `bluetooth-monitor.service` is a COMMENTED candidate, not active: it was
  added after the verified run, never masked live, is not in the Q3 gate,
  and rule "never disable Bluetooth" applies — verify by hand first.
- Live run log with the full falsification trail:
  `models/qnx1d/run-2026-10-29-services-bind.md`.

## What was falsified (do NOT retry)

1. Runtime `mount --bind /bin/true /usr/bin/<name>` + kill: respawner
   bypasses the runtime mount — 19/25 services came back running the
   ORIGINAL binary (forensic: `/proc/<pid>/exe` md5 = original while the
   on-disk path read /bin/true). Bind-mounts may still work AT BOOT (tcc
   does exactly that on the same firmware family, S90D/T-PTMxxxx) — the
   failure mode is runtime-only.
2. Empty files in `/opt/usr/share/systemd/system/<unit>`: systemd's loader
   skips empty unit files.
3. `/dev/null` symlinks in that /opt path: `is-enabled` stayed `static`.
4. Drop-in `foo.service.d/override.conf` with a false
   `ConditionPathExists` in that /opt path: never loaded.
5. Root cause for 2–4, recorded verbatim from the TV:
   `systemctl show -p UnitPath` = `/etc/systemd/system /run/systemd/system
   /run/systemd/generator /usr/lib/systemd/system /prd/usr/lib/systemd/system
   /run/systemd/generator.late` — **`/opt` is not in the path**.
   (The vendor's own `.d/` directories there are inert decorations.)
6. `pkgcmd -k` is a no-op on this firmware. `aulctl is-active` does not
   know svcapps. busybox `ps` shows ~228 of ~408 processes — use `/proc`.
7. Working at runtime: `ln -sf /dev/null /run/systemd/system/<unit>` +
   `systemctl daemon-reload` → `is-enabled` = `masked-runtime`, start
   refused, 13/13 unit-backed services held through an 8 s respawn check.
   **But `/run` is tmpfs — dies at reboot.** That is the gap v42 must fill.

## The v42 proposal under review

`payload/Program.cs` (already runs as root at every boot, ~30–40 s after
power-on via the on-boot app IL replacement) gains a background step, same
pattern as its existing auto-update-off:

1. Read a mask list from persistent storage — e.g.
   `/opt/usr/home/owner/share/debloat-masks.txt` (one unit per line;
   written/shipped by the debloat repo's deploy flow).
2. `ln -sf /dev/null /run/systemd/system/<unit>` for each; then
   `systemctl daemon-reload`.
3. `systemctl stop` each unit; kill any straggler by `/proc/<pid>/exe`
   path under the mapped binaries.
4. Beacon the result (`masks=<n> stopped=<k> fail=<m>`) — the existing
   `Beacon()` with its 500 ms timeout.

## Questions the review must answer

Q1. **Is there an earlier/safer boot vector than the payload?**
   Candidate: `/opt/etc/parseinfo.sh` — a firmware-run boot script (tcc
   replaces it wholesale on the same firmware family and it works there).
   Our `FAILED.md` records that editing it broke the boot service on OUR
   unit (UEP-signed stock file). A cheap falsifiable test exists (append an
   `echo` line, check `/proc/target_version` and boot health, revert).
   If it works, parseinfo could write the /run masks BEFORE systemd starts
   the units — services would never run at all (better than the payload's
   ~30–40 s late window). Weigh: risk of breaking boot vs. a 30 s service
   window.
Q2. **When do the listed units actually start relative to the payload?**
   Check `systemctl show -p ExecMainStartTimestamp <unit>` after a boot vs.
   the payload's first beacon time. If the units start after the payload,
   the payload could mask BEFORE first start (even cleaner: no kill pass
   needed).
Q3. **Does masking break dependencies?** Any unit that `Requires=`/`BindsTo=`
   a masked unit would fail. Check `systemctl list-dependencies` reverse
   edges for the listed units, especially `automation-service`/`factory-service`
   (both 'static' — something pulls them in).
Q4. **Is the payload's boot timing inside systemd's namespace semantics?**
   Round-1 forensics showed runtime bind-mounts bypassed by respawners
   (likely private mount namespaces). /run SYMLINKS are files, not mounts —
   they should be namespace-safe, but confirm: write one mask at runtime,
   verify a respawn attempt is refused (already done for data-service —
   reproduce for one of the respawning units).
Q5. **Anything better entirely?** E.g. a persistent unit path we missed
   (`/prd/usr/lib/systemd/system` is in UnitPath — check if it is writable
   or has an /opt backing), `systemctl edit` equivalents, launchpad/appfw
   config for the daemons, or a vendor disable flag (like the two
   ConditionPathExists units have) present in more unit files — grep
   `/usr/lib/systemd/system` for `ConditionPathExists.*=/opt` to find ALL
   units with vendor opt-file switches; that would extend the free list.
Q6. **Payload discipline (AGENTS.md §9 of samsung_tv_root)**: the new step
   must run on a background thread (never block the channel), beacon with
   the 500 ms cap, fail-open (a missing list file = skip silently), and not
   allocate CLR objects after fork. The list file should ship via the
   debloat repo's flow (deploy-rendered like `rootchan.token`).

## Acceptance criteria for v42 (when built)

After a mains power-cycle, within ~90 s of power-on:
- all 23 listed units masked (`is-enabled` = masked-runtime) and inactive;
- zero processes with exe under the listed units' binaries;
- the 20 `--global` app rows still true;
- channel answering with `id -u` = 0; beacon shows the mask result.
Revert path: remove the list file from /opt → reboot → stock behavior.

## Hard-won facts (do not re-learn)

UEP blocks unsigned ELF and `sh /tmp/file` (`cat file | sh -s` works);
busybox `ps` undercounts (use `/proc`); `pkgcmd -k` no-op; `aulctl
is-active` blind for svcapps; `/proc/mounts` does not list bind mounts
(verify by content md5); never disable `MultiControl-Service` (our
carrier), `coba.adagent`, `org.tizen.menu`/`home.sidebar`, DRM or
Bluetooth; the two privacy-choice UIs stay.

---

# DECISION (2026-10-29, independent review of this brief)

**v42 proposal CONFIRMED as the durable mechanism** — keep /run masks,
re-assert from the payload **after SUCCESS-R00T**, same background-thread
shape as `AutoUpdateOff()` (after uid 0 + `CloseDevice()`, never in front
of `RootChannel()`, fail-open on missing list file). Better than
bind-mounts, better than anything under /opt, safer than `parseinfo.sh`.

Per-question verdicts:
- **Q1 parseinfo: REJECTED as the v42 primary path.** tcc replaces the file
  wholesale because their root dies at reboot; this set has a surviving
  payload. The 30–40 s service window is cheaper than risking the boot path
  that launches MultiControl. Revisit only if Q2 timestamps show the window
  is actually a problem.
- **Q2: assume the payload is LATE.** Cold boots root at ~36–49 s; these
  units are WantedBy multi-user/basic/starter, so they start first. Design
  as mask → stop a running unit → block restart. Keep the stop+kill pass.
  Payload bind-mounts would fail like round 1 (namespaces already exist).
- **Q3 dependency check: was a GATE — CLOSED (see the Q3 GATE RESULT section below).** Reverse
  list-dependencies required for the listed units, especially
  `org.tizen.tv.automation-service` (static) and `factory-service` (ran
  while "disabled") before any payload writes the list.
- **Q4: answered** — /run symlinks are files, not mounts; held through
  respawn. Do not re-prove.
- **Q5: harvest vendor /opt conditions FIRST — they beat v42.** One grep of
  `/usr/lib/systemd/system` for `ConditionPathExists.*=/opt` finds every
  unit with a free durable off-switch (canalysis and pisa are proven
  examples). `/prd/usr/lib/systemd/system` is on UnitPath but treat as
  read-only like /usr. `systemctl edit` targets /etc — read-only.

**List gaps found by the review (fixed in lists/services-units.txt):**
`com.samsung.tv.cis-api-service-app.service` added (launchpad + Restart=
on-failure every 90 s — masking it is how the churn stops; the app row
alone does not). `bt-monitor` = `bluetooth-monitor.service` (candidate,
commented — not `bt-service`). Still unit-less (launchpad, no systemd
unit): `SWUCoreTV`, `SWUService`, `SWUVerifierTV`.

**Acceptance criteria amended:** "zero processes under the listed binaries
within ~90 s" holds only after the kill pass, and only for the units
actually on the list after Q5 + the SWU mapping.

**Remaining live checks** — all done (see UPDATE below). The pre-UPDATE
checklist (Q5 grep, Q3 reverse-deps, SWU/bt-monitor mapping) is closed.

## UPDATE (2026-10-29 late) — both gates CLOSED, v42 cleared

- **Q5 done:** the `/usr/lib/systemd/system` harvest found 9 more units
  with vendor `/opt` switches (airplay-service-2, googlecast-service,
  samsunghealth trio, remote-shop-care-hub, sct-packet-dump,
  lightweight-web-engine-update + mcf-agent flag). They are OWNER-CHOICE
  features — recorded in `models/qnx1d/qnx1d-optional-menu.md` (the
  "Vendor /opt off-switches" section; they are NOT in
  `lists/services-units.txt`), NOT applied. journald/* matched the grep and
  is untouchable.
- **Q3 done:** reverse-dependency gate ran live (`tools/q3deps.sh`): 5
  hard `Requires=` couplings, all documented and accepted (one real
  feature loss: DLNA via vd_dmr depends on register-device — owner
  trade-off, recorded in the list header).
- **SWU mapping done:** SWUCoreTV / SWUService / SWUVerifierTV have no
  units (launchpad); bt-monitor = bluetooth-monitor.service (commented
  candidate — never masked live, see the list).
- **v42 is cleared for implementation** per the confirmed design above.


## Q3 GATE RESULT (2026-10-29 22:0x UTC, live)

Reverse-dependency gate over the then-23-entry mask list (`tools/q3deps.sh`,
run on the TV): **5 hard couplings, all `Requires=`, zero soft-only**.
`bluetooth-monitor.service` is a commented candidate (never masked live) and
is therefore not covered by this gate.

| Masked unit | Hard dependent | Consequence of masking | Verdict |
|---|---|---|---|
| `data-service.service` | `context-aware-service` (Requires) | context-aware never starts (tracking family) | accept |
| `contents-recognition-service.service` | `contents-ui-detector-service` (Requires+Wants) | ACR UI detector down too — more ACR suppressed | accept |
| `p2p-asm.service` | `org.tizen.smsrc.service` (Requires) | screen-mirror remote-control helper down | accept (owner: no mirroring use) |
| `register-device.service` | `vd_dmr.service` (Requires, with dbus.service) | **DLNA media renderer (port 9197) cannot start — casting from phones breaks** | OWNER AWARENESS: kept masked per the approved bind list (tcc does the same); remove this one mask if DLNA casting is ever needed |
| `org.tizen.tv.factory-service.service` | `comss.service` (Requires) | factory/commercial helper down | accept |

**Gate PASSED**: all 5 consequences are either desirable (tracking/ACR/
commercial) or accepted owner trade-offs. One real feature loss identified
and documented (DLNA via `vd_dmr`). The mask list may now be written by the
v42 payload.
