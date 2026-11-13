# Samsung TV Plus opens at power-on — how to stop it

Symptom: the set opens **Samsung TV Plus** (a playing channel, app id
`HEPsqFNie0.tvplusstandalone`) at every power-on, even though
**General & Privacy → Smart Features → Autorun Last App** is disabled. That
switch only covers Smart Hub apps; it does not govern TV Plus.

Two independent controls are involved, and the usual mistake is to change only
one of them.

| Control | Buxton key (system + user) | Where in the UI | What it really does |
|---|---|---|---|
| Autorun Samsung TV Plus | `db/menu/autorun_tv_plus` (bool) | Advanced Features → Start Screen Option (hidden on this model) | The root boot helper creates/removes the marker `/opt/usr/apps/tvplus_autorun_enable`. It does **not** choose the boot screen. |
| Start with Smart Hub Home | `db/menu/smart_hub/ontvsetting/auto_start` (int) | Advanced Features → Start Screen Option | `app-boot-manager` picks the cold-boot target from it: `0` resumes the last source, `1` starts on Smart Hub Home. |

## Why setting only the autorun key is not enough

Measured on the QNX1D (2026-11-13):

- `db/appfw/startup_appid` and `db/appfw/booting_appid_backup` were both
  `org.tizen.tv-viewer`, so a cold boot tunes the **last source**. That source
  was a TV Plus virtual channel (`db/bms-service/current_serviceid` was set),
  so tv-viewer + `slive-provider-daemon` brought the TV Plus web app up.
- `boot-helper-dyboost-tv` (root) contains `handleTvplusAutoRunCallback`, the
  log `key = %s, value = %d(bool)`, and the literal
  `/opt/usr/apps/tvplus_autorun_enable`. Setting `db/menu/autorun_tv_plus` to
  false removes that marker within a second (verified live).
- `app-boot-manager` (firmware `app-boot-manager-1.6.4`, source file
  `src/modes_app_booting_cold_boot_mode.c`) reads
  `db/menu/smart_hub/ontvsetting/auto_start`; its own log line
  `"multiviewbootfile exists and Start with Smart Hub Home Off"` names the
  setting.

So: the autorun key stops TV Plus from being *launched as an app*; the
start-screen key decides whether the TV resumes the last source at all.

## Fix

Over the root channel (`python tools/root_shell.py "<cmd>" <tv-ip>`):

```sh
buxton2ctl set-bool  system db/menu/autorun_tv_plus 0
buxton2ctl set-bool  user   db/menu/autorun_tv_plus 0
buxton2ctl set-int32 system db/menu/smart_hub/ontvsetting/auto_start 1
buxton2ctl set-int32 user   db/menu/smart_hub/ontvsetting/auto_start 1
```

`buxton2ctl set-bool` refuses the word `false` — pass `0`.

## Verify

- Read-back in both layers: `Boolean: False` for the autorun key, `Int32: 1`
  for `auto_start`; `/opt/usr/apps/tvplus_autorun_enable` is absent.
- On the TV: Settings → All Settings → Advanced Features → Start Screen
  Option → **Start with Smart Hub Home** is ON.
- Next **cold boot** (mains; a standby resume will just show the last screen)
  lands on Smart Hub Home, not a TV Plus channel.
- `tools/tv_health.py` does not check these keys — it is the debloat oracle —
  so nothing will report them as drift.

## Revert and trade-offs

- As-found values: `db/menu/autorun_tv_plus = 1`, `auto_start = 0`.
- `auto_start = 1` also stops "resume last app/source": the TV always starts on
  Home. If you want the last app back, leave it `0` and rely on the autorun key
  alone — on this owner's set that was **not** enough (the last-source path
  still reached TV Plus), so both were needed.
- TV Plus stays installed and launches normally when opened manually.

## Does this need root / the boot service?

No service has to run. Both are ordinary settings stored in
`/opt/dbspace`; they survive reboots and the payload/service does not touch
them. "Start with Smart Hub Home" is exposed in the TV menu, so a stock TV can
set it without root. On this model the TV Plus autorun item is hidden
(`db/menu/autorun_tv_plus_state = "hide"`), which is why its key is written
directly — the root channel is only a convenient way to reach the hidden one.
