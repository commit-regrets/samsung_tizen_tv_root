# Samsung updates — and why disabled ad services come back

On 2026-11-12 this set re-enabled three disabled services by itself
(`com.samsung.tv.pisa-service`, `com.samsung.tv.utterance-recommender-app`,
`com.samsung.tv.utterance-recommender-core`) and `pisa-service` /
`adagent-service` started again. Nothing on the PC or the root channel touched
them. Cause: a **preload app update** pushed by Samsung.

This page covers the three update paths, how to turn them off, what an update
does to the debloat store and its vendor sentinels, and how to detect and
restore a reset.

## Three independent update paths

Turning off the firmware switch does **not** stop app updates; they are
separate mechanisms.

| Path | Gate | Where to set it |
|---|---|---|
| Firmware / OTA | `db/menu/support/softwareupdate/autoupdate = 0` (the payload re-asserts it at every boot) | Settings → Support → Software Update → Auto Update |
| Store apps | `db/apps/auto_update = false` (read by `com.samsung.tv.store`'s `CommonStore.dll`) | Smart Hub → Apps → Settings |
| Built-in / preload apps | `db/built-in-app-upgrader/server_upgrade = false` (read by `/usr/apps/org.tizen.was-builtinupgrade/bin/was-builtinupgrade`; the off branch logs `Do not support server upgrade!!`) | no UI — root channel |

The firmware path additionally has thirteen update-related units masked at boot
(3 `fw-update-*` + 10 SWU/VDCA): `fw-update-service.{service,path}`,
`fw-update-init-download.service`, `vdsystem-update-manager.{service,timer}`,
`was-background-update.{service,path}`, `swu-verifier-tv.{service,timer}`,
`swu-core-tv.service`, `swu-service.service`, `vdca-update.service`,
`swu-auto-upgrade.timer`. See `debloat/lists/services-units.txt`.

## What a package update does to the debloat (the "auto re-add")

The 2026-11-12 batch, from `/var/log/appfw/app-installers/installation-history.log`
(times UTC):

```
20261112.171846Z  com.samsung.tv.pisa-service          31.10.2825 -> 31.12.1525  Update SUCCESS
20261112.171902Z  com.samsung.tv.utterance-recommender-service 1.4.2225 -> 1.4.3125  Update SUCCESS
20261112.171908Z  com.samsung.tv.coba.adagent          26.1.6225  -> 26.1.7725   Update SUCCESS
20261112.172041Z  lib-ariafw-tv                        3.007.30090 -> 3.007.40090 Update SUCCESS
```

Two effects, both automated:

1. **The disable rows are reset.** The installer rewrites `package_app_info`
   (`app_disable` back to `false`, `app_package_installed_time` moves), so every
   app id in the updated package is enabled again — the utterance package
   carries both `...-app` and `...-core`, which is why all three came back at
   once.
2. **The vendor sentinel disappears.** `/opt/usr/share/systemd/system/pisa-service`
   vanished 4 s after the pisa update succeeded (directory mtime 18:19:01).
   Both `pisa-service.service` and `adagent-service.service` are gated by
   `ConditionPathExists=!/opt/usr/share/systemd/system/pisa-service`, so with
   the file gone systemd started them at the next boot (18:40:31), and
   `pisa-service.path` — which watches that same path — triggers the service
   as soon as it is missing.

**What the boot payload re-asserts:** `autoupdate = 0`, the 29 unit masks from
`/opt/usr/data/debloat-masks.txt`, and — since **v49**, when the armed marker
`/opt/usr/data/debloat-enforce` exists — the app rows and the two vendor
sentinels. The v49 step makes one read-only `sqlite3` query against
`/opt/dbspace/.pkgmgr_parser.db`, runs `pkgcmd -D --global` only for rows that
are not `true`, re-creates a missing sentinel under
`/opt/usr/share/systemd/system`, stops the three sentinel-gated units, and
beacons `apps n=… missing=… disabled=… absent=… fail=… sentinels=…/… stopped=…`.
`debloat/tools/apply.sh` creates the marker (so a debloated TV repairs itself at
the next boot); `restore.sh` removes it, and a TV that never ran the apply
beacons `apps skip (not armed)` and is left untouched.

## Turn updates off

Over the root channel (`python tools/root_shell.py "<cmd>" <tv-ip>`):

```sh
buxton2ctl set-int32 system db/menu/support/softwareupdate/autoupdate 0
buxton2ctl set-int32 user   db/menu/support/softwareupdate/autoupdate 0
buxton2ctl set-bool  system db/apps/auto_update 0
buxton2ctl set-bool  user   db/apps/auto_update 0
buxton2ctl set-bool  system db/built-in-app-upgrader/server_upgrade 0
buxton2ctl set-bool  user   db/built-in-app-upgrader/server_upgrade 0
```

`set-bool` refuses the word `false` — pass `0`. Persistence: `autoupdate` is
re-asserted at boot by the payload; the other two are one-time writes in
`/opt/dbspace` that survive reboots but are **not** re-applied (a factory reset
or a future firmware update can restore them).

Games have their own switch (`db/games/auto_update`), left alone here.

## What still works

- **Manual** store installs and updates (Smart Hub → Apps → Update/Reinstall),
  including Netflix and Prime Video. Only *automatic* updates stop.
- Apps already installed keep working; TV Plus, Smart Hub and the store are
  untouched.
- What you give up: firmware/security updates and silent preload fixes.

## Detect a reset

- `python tools/tv_health.py --tv <ip>` — checks `applied` (73 expected rows),
  `count`, `off-list` and `sentinels` (2/2). This is what caught 2026-11-12.
- `buxton2ctl` is not enough; the rows live in
  `/opt/dbspace/.pkgmgr_parser.db` (`package_app_info.app_disable`).
- `systemctl is-active pisa-service.service adagent-service.service` — they
  should be `failed`/inactive (condition not met on the sentinel).
- `/var/log/appfw/app-installers/installation-history.log` gains an `Update`
  line per package, and `app_package_installed_time` moves.

## Restore the three services

Use the documented tooling (dry run first; it records the undo log, plants the
sentinel and stops the units):

```sh
# list file on the TV, one bare app id per line
printf '%s\n' \
  'com.samsung.tv.pisa-service' \
  'com.samsung.tv.utterance-recommender-app' \
  'com.samsung.tv.utterance-recommender-core' > /tmp/restore.txt

export APPLY=0; cat /tmp/a.sh | sh -s /tmp/restore.txt   # dry run
export APPLY=1; cat /tmp/a.sh | sh -s /tmp/restore.txt   # real run
```

`/tmp/a.sh` is `debloat/tools/apply.sh` (fetched or pushed; the list must be a
file argument, UEP blocks `sh /tmp/...`). A real run prints
`disabled=3 failed=0 of 3` and `sentinel: pisa-service`, and writes
`/opt/usr/data/debloat-undo-<ts>.sh`. Then re-run `tv_health` (expect 16/16).

## Hard stop if it recurs

If a future path bypasses `server_upgrade`, the durable stop is to mask
`appbinary-manager.service` (DBus, `Type=dbus`) and disable
`org.tizen.was-builtinupgrade`. Both must go through the debloat
list/registry route (`debloat/lists/services-units.txt`, `debloat/registry.tsv`)
so `tv_health` stays green — see `debloat/AGENTS.md`.

## Re-enable

Set the keys back to `1`/`true` (firmware and store toggles are also in the TV
menus). `server_upgrade` has no UI, so use the root channel.
