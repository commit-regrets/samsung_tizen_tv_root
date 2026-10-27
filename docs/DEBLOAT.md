# QNX1D debloat inventory — harvested, reviewed, NOT applied

Status: **inventory only.** Nothing on the TV was disabled, stopped or removed
while producing this. Any apply step is a separate, reviewed change with its own
verify-and-undo story.

## What this is

The 2024 QNX1D test unit exposes **446 packages** through the package registry
(`/opt/dbspace/.pkgmgr_parser.db`, table `package_info`; 295 of them have a
directory under `/opt/usr/apps`). Every package was classified with **Vetro
0.2.3's** catalog rules (`app-catalog.js`: areas, roles and purpose strings
derived from Q80A firmware manifests, T-NKM2DEUC), then kept as a full JSON
inventory.

| Role | Count | Meaning |
|---|---|---|
| `keep` | 240 | the TV relies on it — do not touch |
| `optional` | 160 | a feature you may not use (voice assistants, ambient, sharing, media…) |
| `tracking` | 13 | advertising / viewing-data collection |
| `unused` | 33 | commercial modes only (hotel/EP/shop) on a home set |

Data file: [`debloat/qnx1d-inventory.json`](debloat/qnx1d-inventory.json) — one
record per package: `package`, `type` (wgt/rpk), `mainApp`, `removable`,
`preloaded`, `system`, `disabled` (registry state at harvest time), `area`,
`role`, `purpose`, `referencedBy` (which other packages declare it), `source`
(`firmware manifest` when Vetro's Q80A dump knows the ID, else `name rules`).

## The tracking list (13)

| Package | Purpose |
|---|---|
| `adplatform` | Advertising player |
| `com.samsung.tizen.samsung-analytics` | Collects and uploads usage analytics |
| `com.samsung.tv.ad-web-framework` | Web-based advertising (e.g. in Samsung TV Plus) |
| `com.samsung.tv.adplayer` | Advertising player |
| `com.samsung.tv.canalysis-service` | Content analysis for viewing-information services |
| `com.samsung.tv.cis-api-service-app` | ACR content-information API service |
| `com.samsung.tv.coba.privacy_app` | Privacy choices screen |
| `com.samsung.tv.contents-recognition-dbmgr` | DB for on-screen content recognition |
| `com.samsung.tv.nvision-analysis-dbmgr` | Model manager for on-screen image analysis |
| `com.samsung.tv.pisa-service` | Personalised content/ads for Smart Hub |
| `com.samsung.tv.targeted-ad-service` | Selects targeted advertising |
| `content-grab-service` | Captures frames of the current picture |
| `tv6pbVMQFF` | Privacy choices web app |

Two of these are **not** disable candidates despite the role: the two privacy
choice screens (`coba.privacy_app`, `tv6pbVMQFF`) are the UI that *lets the
normal user* set ad preferences — Vetro's own catalog force-keeps them.

## Method (reproduce it)

```sh
# on the TV, via the root channel:
ls /opt/usr/apps/
sqlite3 -separator '|' /opt/dbspace/.pkgmgr_parser.db \
  "select package, package_type, package_removable, package_preload, \
          package_system, package_disable, mainapp_id \
   from package_info order by package;"
# merge with Vetro's rules (its MIT-licensed catalog):
# (edit the input path inside, then:)
node tools/debloat_merge.js   # writes docs/debloat/qnx1d-inventory.json
```

Provenance: classification by [Vetro](https://github.com/andrearicci93/vetro)
0.2.3 (`app/service/app-catalog.js`, MIT), whose rules were derived from Q80A
manifests on Tizen 6. **Cross-firmware caveat:** the rules matched many
packages here directly — including the obfuscated store IDs (`30IKH0OX8U`,
`9Ur5IzDKqV`) that also exist on this Tizen 9 build — but a `name rules`
classification (no manifest behind it) is guidance, not ground truth. Anything
you act on should be confirmed against this firmware's own registry row and
`referencedBy` list first.

## How a disable would work (NOT executed yet)

The registry has the switches the debloater uses: `package_disable`,
`package_support_disable` in `package_info`, plus per-app boot flags and
`aulctl`. A safe apply shape, when we do it:

1. dry-run print: package → current state → command;
2. one package at a time, never a batch, never a `keep`/`system`/non-removable
   without an explicit override;
3. after each: read the registry back, confirm the service did not restart,
   confirm the TV still boots the payload (channel returns);
4. one-line undo per package recorded before the command runs.

Deleting (`pkgmgr uninstall`) is out of scope for the first pass: disable is
reversible, uninstall on a preloaded/system package may not be.

## Vetro on this TV

The long-term idea is to drive [Vetro](https://github.com/andrearicci93/vetro)'s
dashboard (its debloater/privacy UX) from our root channel instead of its own
SDB-based root route, which is closed on this chassis (see `docs/FAILED.md`:
sdb whitelist-only, `sdbd` root capability unimplemented, installer write with
no exec consumer, UEP unsigned-exec block). This inventory is step one of that:
its debloater needs exactly this per-package registry state.
