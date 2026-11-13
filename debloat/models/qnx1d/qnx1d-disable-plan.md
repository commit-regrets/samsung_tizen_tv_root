# QNX1D disable plan — DRY RUN (nothing executed)

Generated 2026-10-27 from `models/qnx1d/qnx1d-inventory.json` (the file was
then under a `docs/debloat/` path in the sibling repo; it moved here).
SUPERSEDED for day-to-day use by `lists/*.txt` (tier1/tier2a) and the
`--global` switch (the `--uid` form below does not persist; kept for the
record). The live lists are in `debloat/lists/`.
Mechanism: `pkgcmd -D/-A -t app -n <app_id> --global` (root). That writes
`package_app_info.app_disable` in `/opt/dbspace/.pkgmgr_parser.db`.
`--uid` does not write the row (session-only). A second `--global` on an
already-disabled app returns "Failed to get appinfo"; read the sqlite flag.

Protected (excluded from this plan):
  com.samsung.tv.coba.privacy_app, tv6pbVMQFF (privacy-choice UIs — user-facing)
  com.samsung.tv.coba.adagent (Vetro Smart Hub dependency guard, not present here but kept)

| # | app_id | purpose | current onboot/autorestart | disable command | undo command |
|---|---|---|---|---|---|
| 1 | adplatform.ADPlayer | Advertising player. | (see package_app_info) | `pkgcmd -D -t app -n adplatform.ADPlayer --global` | `pkgcmd -A -t app -n adplatform.ADPlayer --global` |
| 2 | com.samsung.tizen.samsung-analytics | Collects and uploads Samsung usage analytics. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tizen.samsung-analytics --global` | `pkgcmd -A -t app -n com.samsung.tizen.samsung-analytics --global` |
| 3 | com.samsung.tv.ad-web-framework | Shows web-based advertising, for example in Samsung TV Plus. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.ad-web-framework --global` | `pkgcmd -A -t app -n com.samsung.tv.ad-web-framework --global` |
| 4 | com.samsung.tv.adplayer | Advertising player. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.adplayer --global` | `pkgcmd -A -t app -n com.samsung.tv.adplayer --global` |
| 5 | com.samsung.tv.canalysis-service | Content analysis daemon used by viewing-information services. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.canalysis-service --global` | `pkgcmd -A -t app -n com.samsung.tv.canalysis-service --global` |
| 6 | com.samsung.tv.cis-api-service-app | API service for content information (ACR). | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.cis-api-service-app --global` | `pkgcmd -A -t app -n com.samsung.tv.cis-api-service-app --global` |
| 7 | com.samsung.tv.contents-recognition-dbmgr | Database for on-screen content recognition. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.contents-recognition-dbmgr --global` | `pkgcmd -A -t app -n com.samsung.tv.contents-recognition-dbmgr --global` |
| 8 | com.samsung.tv.nvision-analysis-dbmgr | Model manager for on-screen image analysis. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.nvision-analysis-dbmgr --global` | `pkgcmd -A -t app -n com.samsung.tv.nvision-analysis-dbmgr --global` |
| 9 | com.samsung.tv.pisa-service | Personalised content and advertising service for Smart Hub. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.pisa-service --global` | `pkgcmd -A -t app -n com.samsung.tv.pisa-service --global` |
| 10 | com.samsung.tv.targeted-ad-service | Selects targeted advertising. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.targeted-ad-service --global` | `pkgcmd -A -t app -n com.samsung.tv.targeted-ad-service --global` |
| 11 | content-grab-service | Captures frames of the current picture for content services. | (see package_app_info) | `pkgcmd -D -t app -n content-grab-service --global` | `pkgcmd -A -t app -n content-grab-service --global` |

## Apply protocol (this dry run was approved and executed 2026-10-29)

1. One package at a time; run disable, then read back:
   sqlite3 package_info.package_disable / package_app_info state for that app;
   ps check: no new/lingering process of that name.
2. Record undo line BEFORE the disable (table above).
3. After each package: root channel still answers (id -u = 0).
4. Stop at the first unexpected result; undo that package.
5. Full pass ends with: payload health check + a reboot (channel must
   return on its own), then re-run this plan file as a diff of states.

Note: none of these 11 services was running at idle (ps, 2026-10-27) —
they are demand-started; targeted-ad-service carries app_onboot=true,
so the practical effect to verify after disabling is boot-time, not CPU.

## Batch 2 — commercial/unused (30 of 33; 3 coupled skipped)

Hotel/EP/factory components on a home set. Coupling check against the
keep set: 30 reference nothing we keep. Skipped as coupled: `org.tizen.ep-hotel-channel` (referenced by function-osd), `org.tizen.ep-hotel-factory` (referenced by tv-viewer/homesetting/broadcastingmenu/swu/...), `org.tizen.factory` (referenced by tv-viewer/ug-hbbtv-efl).

| # | app_id | purpose | disable | undo |
|---|---|---|---|---|
| 1 | com.samsung.ep-plateau-agent | com.samsung.ep-plateau-agent | `pkgcmd -D -t app -n com.samsung.ep-plateau-agent --global` | `pkgcmd -A -t app -n com.samsung.ep-plateau-agent --global` |
| 2 | com.samsung.ep-plateau-agent-service | com.samsung.ep-plateau-agent-service | `pkgcmd -D -t app -n com.samsung.ep-plateau-agent-service --global` | `pkgcmd -A -t app -n com.samsung.ep-plateau-agent-service --global` |
| 3 | com.samsung.ep-plateau-info | com.samsung.ep-plateau-info | `pkgcmd -D -t app -n com.samsung.ep-plateau-info --global` | `pkgcmd -A -t app -n com.samsung.ep-plateau-info --global` |
| 4 | com.samsung.ep-tbmapp-launcher | com.samsung.ep-tbmapp-launcher | `pkgcmd -D -t app -n com.samsung.ep-tbmapp-launcher --global` | `pkgcmd -A -t app -n com.samsung.ep-tbmapp-launcher --global` |
| 5 | com.samsung.ep.coba.hotel | CoBA Hotel Component | `pkgcmd -D -t app -n com.samsung.ep.coba.hotel --global` | `pkgcmd -A -t app -n com.samsung.ep.coba.hotel --global` |
| 6 | com.samsung.ep.hotel-popup | com.samsung.ep.hotel-popup | `pkgcmd -D -t app -n com.samsung.ep.hotel-popup --global` | `pkgcmd -A -t app -n com.samsung.ep.hotel-popup --global` |
| 7 | com.samsung.ep.hotel-quicksetting-editor | com.samsung.ep.hotel-quicksetting-editor | `pkgcmd -D -t app -n com.samsung.ep.hotel-quicksetting-editor --global` | `pkgcmd -A -t app -n com.samsung.ep.hotel-quicksetting-editor --global` |
| 8 | com.samsung.ep.hotel.uigadgets | com.samsung.ep.hotel.uigadgets | `pkgcmd -D -t app -n com.samsung.ep.hotel.uigadgets --global` | `pkgcmd -A -t app -n com.samsung.ep.hotel.uigadgets --global` |
| 9 | com.samsung.hitcomp | hitcomp | `pkgcmd -D -t app -n com.samsung.hitcomp --global` | `pkgcmd -A -t app -n com.samsung.hitcomp --global` |
| 10 | com.samsung.tv.coba.plateauhome | com.samsung.tv.coba.plateauhome | `pkgcmd -D -t app -n com.samsung.tv.coba.plateauhome --global` | `pkgcmd -A -t app -n com.samsung.tv.coba.plateauhome --global` |
| 11 | com.samsung.tv.demo-player | com.samsung.tv.demo-player | `pkgcmd -D -t app -n com.samsung.tv.demo-player --global` | `pkgcmd -A -t app -n com.samsung.tv.demo-player --global` |
| 12 | ep-hotel-protocol | ep-hotel-protocol | `pkgcmd -D -t app -n ep-hotel-protocol --global` | `pkgcmd -A -t app -n ep-hotel-protocol --global` |
| 13 | ep-log-manager | ep-log-manager | `pkgcmd -D -t app -n ep-log-manager --global` | `pkgcmd -A -t app -n ep-log-manager --global` |
| 14 | org.tizen.AgingApp | AgingApp | `pkgcmd -D -t app -n org.tizen.AgingApp --global` | `pkgcmd -A -t app -n org.tizen.AgingApp --global` |
| 15 | org.tizen.UsbSyncDisplay | UsbSyncDisplay | `pkgcmd -D -t app -n org.tizen.UsbSyncDisplay --global` | `pkgcmd -A -t app -n org.tizen.UsbSyncDisplay --global` |
| 16 | org.tizen.automation-alert | automation-alert | `pkgcmd -D -t app -n org.tizen.automation-alert --global` | `pkgcmd -A -t app -n org.tizen.automation-alert --global` |
| 17 | org.tizen.automation-app | automation-app | `pkgcmd -D -t app -n org.tizen.automation-app --global` | `pkgcmd -A -t app -n org.tizen.automation-app --global` |
| 18 | org.tizen.automation-viewer | automation-viewer | `pkgcmd -D -t app -n org.tizen.automation-viewer --global` | `pkgcmd -A -t app -n org.tizen.automation-viewer --global` |
| 19 | org.tizen.cloning | cloning | `pkgcmd -D -t app -n org.tizen.cloning --global` | `pkgcmd -A -t app -n org.tizen.cloning --global` |
| 20 | org.tizen.ep-hotel-alarm | EP Hotel Alarm | `pkgcmd -D -t app -n org.tizen.ep-hotel-alarm --global` | `pkgcmd -A -t app -n org.tizen.ep-hotel-alarm --global` |
| 21 | org.tizen.ep-hotel-channellist | Channel-list Application | `pkgcmd -D -t app -n org.tizen.ep-hotel-channellist --global` | `pkgcmd -A -t app -n org.tizen.ep-hotel-channellist --global` |
| 22 | org.tizen.ep-hotel-popup-ui | ep-hotel-popup-ui | `pkgcmd -D -t app -n org.tizen.ep-hotel-popup-ui --global` | `pkgcmd -A -t app -n org.tizen.ep-hotel-popup-ui --global` |
| 23 | org.tizen.ep-hotel-protocolui | ephotel-protocolui | `pkgcmd -D -t app -n org.tizen.ep-hotel-protocolui --global` | `pkgcmd -A -t app -n org.tizen.ep-hotel-protocolui --global` |
| 24 | org.tizen.ep-hotel-security | ep-hotel-security | `pkgcmd -D -t app -n org.tizen.ep-hotel-security --global` | `pkgcmd -A -t app -n org.tizen.ep-hotel-security --global` |
| 25 | org.tizen.ep-system-manager | ep-system-manager | `pkgcmd -D -t app -n org.tizen.ep-system-manager --global` | `pkgcmd -A -t app -n org.tizen.ep-system-manager --global` |
| 26 | org.tizen.ephotel-cloning | hotelcloning | `pkgcmd -D -t app -n org.tizen.ephotel-cloning --global` | `pkgcmd -A -t app -n org.tizen.ephotel-cloning --global` |
| 27 | org.tizen.factory-analysis-viewer | org.tizen.factory-analysis-viewer | `pkgcmd -D -t app -n org.tizen.factory-analysis-viewer --global` | `pkgcmd -A -t app -n org.tizen.factory-analysis-viewer --global` |
| 28 | org.tizen.remote-service-logging-debug-menu | Remote Service Debug Menu | `pkgcmd -D -t app -n org.tizen.remote-service-logging-debug-menu --global` | `pkgcmd -A -t app -n org.tizen.remote-service-logging-debug-menu --global` |
| 29 | org.tizen.rscm-screensaver | Remote Shop Content Management | `pkgcmd -D -t app -n org.tizen.rscm-screensaver --global` | `pkgcmd -A -t app -n org.tizen.rscm-screensaver --global` |
| 30 | org.tizen.widget_viewer_sdk | Widget Viewer for SDK | `pkgcmd -D -t app -n org.tizen.widget_viewer_sdk --global` | `pkgcmd -A -t app -n org.tizen.widget_viewer_sdk --global` |

## Batch 3 — EXECUTED 2026-10-30 as VOICE ONLY (`lists/batch3-optional.txt`)

**The sharing half was reverted the same evening.** The first run disabled 38
ids (voice 22 + sharing 16) and SmartThings phone control broke:
`com.samsung.tizen.smartthings-client` declares `com.samsung.tv.multiscreen` in
the inventory `referencedBy`, and multiscreen was in the disabled set. All 16
sharing ids were re-enabled (`pkgcmd -A`), rows went 58 -> 42, the
`multiscreen` mask entry was removed and the unit unmasked+started. The file
keeps the reverted block with the reason and the "if you want the AirPlay
receiver's 7.3 MB back, bisect one id at a time against a phone test" note.



Owner decisions: **no voice**, **no AirPlay / Multi View / screen mirroring**,
**SmartThings IS used** (phone control), so:
- voice: all 23 ids minus `org.tizen.multi-assistant-service` (already disabled
  in tier 2a) = 22;
- sharing: 16 of 18 - `com.samsung.tv.coba.mobilebff` kept (CoBA mobile backend,
  a phone-control path could ride on it) and `org.tizen.5-way-function` /
  `...airplay-app-2-dummy` skipped because they are not installed here (the
  *real* `com.samsung.tv.airplay-app-2` was added instead - the menu only lists
  the dummy);
- **`samsung` untouched** (SmartThings, Samsung account, Cloud, Pass, SSO).

Result: dry run 38/38, real run 38/38 disabled, 0 failed, rows 20 -> 58, undo
`/opt/usr/data/debloat-undo-20261030-155433.sh`. Only `airplay-app-2` was
resident (~7.3 MB PSS) and was killed; the rest is "never launches again".
The disable exposed `com.samsung.tv.multiscreen.service` restarting every 5 s -
added to the mask list (34 -> 35), which v42 then masked (`masks=35 ... activating=0`).

**Reverted the same evening.** The 16 sharing ids were re-enabled and that
mask entry removed. The phone-offline cause turned out to be
`org.tizen.easysetup-daemon` (tier 2a) - denylisted now, and its unit is off
the mask list too. Final standing set: **37 app rows / 29 units**.

## Batch 3 (original menu framing, for reference)

Nothing here is pre-planned: these are user-facing features. The full
menu with purposes and reverse-dependencies is in
`models/qnx1d/qnx1d-optional-menu.md`. Area defaults proposed:

- **voice** — disable ONLY if the voice remote/mic features are never used (23 pkgs; kills Bixby/Alexa/wakeup engines; the remote mic button stops working)
- **ambient** — safe to disable on a non-Art-Mode household (14 pkgs)
- **sharing** — disable only if Multi View/AirPlay/mirroring are never used (21 pkgs)
- **devices** — CAUTION: includes Bluetooth framework pieces — a BT remote/audio dies with it (32 pkgs; pick individually)
- **samsung** — disable only if Samsung account/SmartThings/store billing are never used (32 pkgs)
- **support** — mostly remote-diagnostics; moderate (13 pkgs)
- **media** — CAUTION: includes store/streaming apps you may want (25 pkgs; pick individually)

Mark the areas (or individual app_ids) and they are appended to the plan
with per-package commands exactly like batch 1/2.
