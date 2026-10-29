# samsung-tv-debloat

Root-powered debloating for Samsung Tizen TVs: reviewed per-model package
inventories, disable lists with per-line undo, and a measured
resource budget. Disable only — never uninstall — so everything reverses
from the same list.

**Contract:** this folder needs exactly one thing — a root shell on the TV
speaking the 31337 line protocol. That shell is provided by the rooting
toolkit in this same repository (`root.ps1` / `tools/root_shell.py`); this
folder never roots anything itself and has no opinion about how the root
was obtained. The payload (v42, pending) will re-assert the service mask
list from the root-owned policy path at every boot.

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
bind-list argument, refuses unit names that have no unit file, and kills
leftover `/usr/bin/<name>` processes after stop.

## Status

- **Tiers 1+2a (20 packages) applied live 2026-10-29** — durably disabled
  via `pkgcmd -D --global`. Post-boot readback: the 11 tier-1 rows are
  **cold-boot verified** (2026-10-29 mains cycle); the 9 tier-2a rows were
  read back after the run but have not had their own cold-boot readback —
  the store and the mechanism are the same (run log:
  `models/qnx1d/run-2026-10-29-tier1.md`). ~25.9 MB running ACR/ad
  processes freed (distinct processes, measured against the pre-debloat
  baseline).
- **Services layer: 23 systemd units masked live** via `/run` masks
  (`tools/mask.sh`) — session-only by design; the verified round-4 run
  (2026-10-29) masked 23/23 and nothing respawned in the 8 s check,
  ~192 MB sum-RSS across the 21 running `/usr/bin` services (upper bound;
  the per-process dump is the evidence). Durable suppression = the boot
  payload re-writing the masks each boot (v42, not started). Full
  falsification trail (empty /opt files, /opt symlinks and drop-ins all
  inert — `/opt` is not in systemd's UnitPath; runtime bind-mounts
  bypassed) in `models/qnx1d/run-2026-10-29-services-bind.md`.
- `bluetooth-monitor.service` is a **commented candidate**, not an active
  mask: it was added after the verified run, has never been masked live,
  was not in the Q3 reverse-dependency gate, and the v42 brief says never
  disable Bluetooth. Enable it only after one manual mask with the BLE
  remote/audio checked.
- Formerly "unit-less" daemons resolved and on the mask list:
  TIFADaemon_L <- automation-service, TIFSDaemon <- factory-service,
  SCSAgent <- scs-agent.service, SWUAutoUpgrade <- swu-auto-upgrade.service.
  Genuinely unit-less (launchpad, respawn regardless, ~29 MB):
  `SWUCoreTV`, `SWUService`, `SWUVerifierTV` — suppression route still open.

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
  - `lists/services-units.txt` (23 masked units, plus a commented
    `bluetooth-monitor.service` candidate) + `lists/services-bind.txt`
    (25 `/usr/bin` binaries — now the **kill list** for `mask.sh`, not a
    bind-mount list; bind-mount overlaying was falsified, respawner bypass,
    and its scripts were removed). The runtime tool is
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
