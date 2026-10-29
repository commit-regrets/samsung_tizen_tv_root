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
                       apply.sh / restore.sh (TV-side, busybox sh)
```

## Quick start (after rooting)

```sh
# on the PC, from the repo root (tools/root_shell.py drives the 31337
# channel).  Serve the debloat folder with any static server, then per list:
python -m http.server 8090 -d debloat/
python tools/root_shell.py "curl -s http://<pc>:8090/tools/apply.sh -o /tmp/a.sh && curl -s http://<pc>:8090/lists/tier1-tracking.txt -o /tmp/l.txt && cat /tmp/a.sh | sh -s /tmp/l.txt" <tv-ip>
# NOTE: UEP blocks `sh /tmp/file` - the `cat file | sh` pipe form is required.
# The dry run is the same command with APPLY=0 in front of sh.
```

`apply.sh` refuses to run without the list, validates every entry as a bare
package/app id before it reaches a shell, keeps a `coba.adagent` /
privacy-UI hard-denylist, records the undo line for every package *before*
disabling it, and prints a summary with a per-package failure count.

## Status

- **Tiers 1+2a (20 packages) applied live 2026-10-29** — durably disabled
  via `pkgcmd -D --global` (parser DB, cold-boot verified); ~25.9 MB running
  ACR/ad processes freed (run log: `models/qnx1d/run-2026-10-29-tier1.md`).
- **Services layer (13 systemd units, ~190 MB idle RSS) suppressed live**
  via `/run` masks (`tools/mask.sh`) — session-only by design; durable
  suppression = the boot payload re-writing the masks each boot (v42, not
  started). Full falsification trail (empty /opt files, /opt symlinks and
  drop-ins all inert — `/opt` is not in systemd's UnitPath; runtime
  bind-mounts bypassed) in `models/qnx1d/run-2026-10-29-services-bind.md`.
- Formerly "unit-less" daemons resolved and on the mask list:
  TIFADaemon_L <- automation-service, TIFSDaemon <- factory-service,
  SCSAgent <- scs-agent.service, SWUAutoUpgrade <- swu-auto-upgrade.service.
  Genuinely unit-less (launchpad, respawn regardless, ~29 MB):
  `SWUCoreTV`, `SWUService`, `SWUVerifierTV` — forensics pending.

**Pre-debloat baseline captured** (`models/qnx1d/baseline-pre-debloat.txt`:
  meminfo, PSI, load, per-process VmRSS+exe, disabled-row count) — the A/B
  comparison after any apply diffs against this file.
- **Tiered lists** (tracking re-classified with the current Vetro catalog,
  cross-merged with tizen-tv-control-center's S90D list, same firmware family):
  - `lists/tier1-tracking.txt` (11): tracking role, standalone-safe. Two
    catalog-tracking packages are deliberately NOT listed:
    `screen-analysis-dbmgr` (tcc measured picture-processing breakage) and
    `iacr` (coupling unknown — review first).
  - `lists/tier2a-tcc-apps.txt` (9): tcc list ∩ registry, optional/tracking,
    uncoupled.
  - `lists/tier2b-home-dependent.txt` (22, commented): tcc apps that are
    Vetro-keep or keeper-coupled — only with Home replacement or explicit
    owner acceptance.
  - `lists/services-bind.txt` (25) + `lists/services-units.txt` (23 units):
    the `/usr/bin` binaries and their systemd units. The runtime tool is
    `tools/mask.sh` / `tools/unmask.sh` (**working**: `/run` masks,
    session-only — mask + reload + stop + refusal test, idempotent);
    bind-mount overlaying was falsified (respawner bypasses runtime
    mounts) and its scripts removed; the
    baseline was captured before any overlay).
  - Older per-source lists (`batch1`, `batch2`) and `models/qnx1d/optional-menu.md`
    remain for review.
- Measured idle-RSS budget per group is in `models/qnx1d/resource-math.md`.

## Safety

Run only on hardware you own. Disabling the wrong package can degrade TV
features; every list here says which entries are coupled to kept components.
The root channel that enables this is a LAN backdoor — keep the TV on a
network you control. See `../SECURITY.md`.

## Attribution

- Package classification: [Vetro](https://github.com/andrearicci93/vetro)
  0.2.3 `app-catalog` rules (Q80A manifests), MIT — see
  `THIRD_PARTY_NOTICES.md`.
- List-file discipline inspired by
  [cleanyourtv](https://github.com/Gathin23/cleanyourtv) (one package per
  line, validated bare names, restore from the same list).
- Rooting is out of scope here; see the rooting toolkit's own docs and
  licenses.
