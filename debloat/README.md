# samsung-tv-debloat

Root-powered debloating for Samsung Tizen TVs: reviewed per-model package
inventories, disable lists with per-line undo, and a measured
resource budget. Disable only — never uninstall — so everything reverses
from the same list.

**Contract:** this folder needs exactly one thing — a root shell on the TV
speaking the 31337 line protocol. That shell is provided by the rooting
toolkit in this same repository (`root.ps1` / `tools/root_shell.py`); this
folder never roots anything itself and has no opinion about how the root
was obtained. The payload (v42, deployed 2026-10-30) re-asserts the service mask list
from the root-owned policy path at every boot.

## Layout

```
models/<model>/        per-model inventory + plans + measurements
  qnx1d/               2024 Neo QLED (QNX1D, Tizen 9, QTV T09): 446 packages
                       classified with Vetro 0.2.3's catalog; measured idle
                       RAM per disable group
lists/                 owner-choosable disable lists (one app_id per line,
                       # comments, restore runs the same file)
tools/                 merge (registry dump + catalog -> inventory),
                       apply.sh / restore.sh / mask.sh / unmask.sh (TV-side),
                       q3deps.sh (reverse-dependency gate for the unit list)
```

## Quick start (after rooting)

```sh
# on the PC, from the repo root (tools/root_shell.py drives the 31337
# channel).  Serve the debloat folder, then push one list at a time:
#   * Windows: use pysrv.exe, NOT python.exe.  This PC's firewall has
#     inbound Block rules for python.exe and Allow rules for pysrv.exe
#     (parent AGENTS.md), so a python.exe server answers on loopback and is
#     unreachable from the TV - no page, no beacons, no error to explain it.
#   * Linux/macOS: python3 is fine.
pysrv.exe -m http.server 8090 -d debloat/         # Windows
python3 -m http.server 8090 -d debloat/           # Linux/macOS
python tools/root_shell.py "curl -s http://<pc>:8090/tools/apply.sh -o /tmp/a.sh && curl -s http://<pc>:8090/lists/tier1-tracking.txt -o /tmp/l.txt && cat /tmp/a.sh | sh -s /tmp/l.txt" <tv-ip>
# NOTE: UEP blocks `sh /tmp/file` - the `cat file | sh` pipe form is required.
# The dry run is the same command with APPLY=0 in front of sh.
```

`apply.sh` requires the list as a **file argument** and refuses to run
without one (exit 2): a list piped on stdin cannot be supported, because the
usual invocation pipes the *script* in and stdin is then the script. It
validates every entry as a bare package/app id before it reaches a shell,
keeps a hard denylist (carrier, adagent, privacy UIs, Home/menu, DRM,
screen-analysis, Vetro), plants the canalysis/pisa vendor sentinels, records
the undo line *before* each disable under `/opt/usr/data/` (replay with
`cat file | sh` — UEP blocks `sh /path`), and prints a summary with a
per-package failure count. A dry run exits non-zero on a refused entry, so
`APPLY=0` is a real gate. `mask.sh` takes a unit list plus an optional
bind-list argument, refuses unit names that have no unit file, kills
leftover `/usr/bin/<name>` processes after stop, installs the persistent
picture-settings loop, and fails if a listed unit is still restart-looping.

## Status

- **Tiers 1+2a (20 packages) applied live 2026-10-29** — durably disabled
  via `pkgcmd -D --global`. **All 20 rows are cold-boot verified**
  (2026-10-30 mains cycle: `id -u` = 0, count = 20, both sentinels present;
  the 11 tier-1 rows were first confirmed 2026-10-29). Run log:
  `models/qnx1d/run-2026-10-29-tier1.md`. ~25.9 MB running ACR/ad
  processes freed (distinct processes, measured against the pre-debloat
  baseline).
- **Services layer: a 29-unit mask list, all of it masked durably (v42) and
  verified on the 2026-10-30 cold boot** (`masks=24 ... listed-activating=0` on
  the then-24-unit list), then 34 with the OTA stack at 14:50, and **29 since
  that evening** (the four phone-path units and the
  `org.tizen.easysetup-daemon.service` mask were removed for SmartThings). The
  standing set was applied live 18:56 (`masks=29 stopped=29 killed=4 fail=0
  missing=0 activating=0 listed-activating=0 loop-check=ok`) with the phone
  **online** (owner-confirmed). The **first 29-unit cold boot passed
  2026-10-30 19:29:41** (`masks begin n=29`, `masks=29 stopped=29 killed=4
  fail=0 missing=0 activating=1 listed-activating=0 loop-check=ok`, with the
  easysetup unit active and `NRestarts=0`). The verified round-4 run
  (2026-10-29) masked 23/23 and nothing respawned in the 8 s check,
  ~192 MB sum-RSS across the 21 running `/usr/bin` services (upper bound;
  the per-process dump is the evidence). The 24th,
  `org.tizen.easysetup-daemon.service`, was added 2026-10-30: the new
  restart-loop check found its unit spinning at `NRestarts=654`
  (`activating (auto-restart)`) because its app is disabled in tier 2a and
  `Restart=on-failure` retries a launcher call that can never succeed; it
  was verified by masking that one unit, not in a full run. **Removed again
  2026-10-30 evening:** either the app disable or the unit mask makes the
  owner's phone show the TV offline, so the daemon runs and its unit is not
  masked.
  Durable suppression = the boot
  payload re-applying the masks each boot from
  `/opt/usr/data/debloat-masks.txt` (v42, deployed 2026-10-30 and **cold-boot
  verified**: every mask back, none active, zero listed processes; 29/29 since
  the 2026-10-30 evening cuts). Full
  falsification trail (empty /opt files, /opt symlinks and drop-ins all
  inert — `/opt` is not in systemd's UnitPath; runtime bind-mounts
  bypassed) in `models/qnx1d/run-2026-10-29-services-bind.md`.
- **Picture settings** are guarded two ways since 2026-10-30: the immediate
  `SetNewHome int32:0` + verify, and the persistent `newhome-fix` 30 s loop
  (`systemd-run`, tcc's proven form). A one-shot is not enough — the flag
  can be re-set mid-session; `systemctl stop newhome-fix` removes it.
- `bluetooth-monitor.service` is **excluded on the owner's instruction**
  (mask list *and* kill list). Checked live 2026-10-30: it is the boot-time
  Bluetooth re-activator — its unit comment is "bt-service check previous
  BT-connection status and re-activate BT when boot", it is wanted by
  `starter.target` + `swu-standalone.target`, the running `bt-monitor` holds
  `/dev/micom-msg` and `/dev/eeprom`, and it restarts 2 s after any abnormal
  exit. tcc blocks it and reports the remote still works, but that is
  unverified on this set; ~5.8 MB is not worth the experiment.
- Formerly "unit-less" daemons resolved and on the mask list:
  TIFADaemon_L <- automation-service, TIFSDaemon <- factory-service,
  SCSAgent <- scs-agent.service, SWUAutoUpgrade <- swu-auto-upgrade.service.
  Not unit-less after all (corrected 2026-10-30): `SWUCoreTV`, `SWUService`
  and `SWUVerifierTV` ship `swu-core-tv.service`, `swu-service.service` and
  `swu-verifier-tv.service`; all three units joined the durable mask list
  together with the rest of the OTA stack (29 units total after the evening
  cuts).
  `p2p-asm-UI` stays genuinely unit-less (launchpad, respawns regardless).

**Pre-debloat baseline captured** (`models/qnx1d/baseline-pre-debloat.txt`:
  meminfo, PSI, load, per-process VmRSS+exe, disabled-row count) — the A/B
  comparison after any apply diffs against this file.
- **Tiered lists** (tracking re-classified with the current Vetro catalog,
  cross-merged with tizen-tv-control-center's S90D list, same firmware family):
  - `lists/tier1-tracking.txt` (11): tracking role, standalone-safe. Two
    catalog-tracking packages are deliberately NOT listed and are denylisted
    in `apply.sh`:
    `screen-analysis-dbmgr` (tcc measured picture-processing breakage) and
    `iacr` (coupling unknown — review first; not denylisted, but not in any
    tier).
  - `lists/tier2a-tcc-apps.txt` (9): tcc list ∩ registry, optional/tracking,
    uncoupled.
  - `lists/tier2b-home-dependent.txt` (22, commented): tcc apps that are
    Vetro-keep or keeper-coupled — only with Home replacement or explicit
    owner acceptance.
  - `lists/services-units.txt` (24 masked units; `bluetooth-monitor.service`
    is a commented DO-NOT-MASK note with the evidence) +
    `lists/services-bind.txt` (24 `/usr/bin` binaries — the **kill list** for
    `mask.sh`, not a bind-mount list; `bt-monitor` is commented out for the
    same reason; bind-mount overlaying was falsified, respawner bypass, and
    its scripts were removed). The runtime tool is
    `tools/mask.sh` / `tools/unmask.sh` (**working**: `/run` masks,
    session-only — mask + reload + stop + refusal test, idempotent; it
    refuses unit names with no unit file). `tools/q3deps.sh` is the
    reverse-dependency gate for the unit list. The baseline was captured
    before any overlay.
  - Older per-source lists (`batch1`, `batch2`) and `models/qnx1d/optional-menu.md`
    remain for review.
- Idle-RSS upper bounds per group are in `models/qnx1d/resource-math.md`
  (baseline, pre-run: sum-of-RSS upper bounds, not freed pages). The
  measured result is the per-process A/B diff in the run logs.

## Safety

Run only on hardware you own. Disabling the wrong package can degrade TV
features; every list here says which entries are coupled to kept components.
The root channel that enables this is a LAN backdoor — keep the TV on a
network you control. See `../SECURITY.md`.

## Attribution

- Package classification: [Vetro](https://github.com/andrearicci93/vetro)
  0.2.3 `app-catalog` rules (Q80A manifests), MIT — see
  [`third_party/vetro/LICENSE`](third_party/vetro/LICENSE).
- List-file discipline inspired by
  [cleanyourtv](https://github.com/Gathin23/cleanyourtv) (one package per
  line, validated bare names, restore from the same list).
- Rooting is out of scope here; see the rooting toolkit's own docs and
  licenses.
