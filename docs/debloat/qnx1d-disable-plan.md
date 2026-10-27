# QNX1D disable plan — DRY RUN (nothing executed)

Generated 2026-10-27 from docs/debloat/qnx1d-inventory.json.
Mechanism: Vetro 0.2.3 debloat-commands.js => pkgcmd -D/-A -t app -n <app_id> --uid <owner>.
Owner uid resolved at run time: stat -c %u /opt/usr/home/owner (5001).
Verified live: pkgcmd accepts -D (probe with a nonexistent app returned
"Failed to get appinfo" — i.e. the flag parses; no state was changed).

Protected (excluded from this plan):
  com.samsung.tv.coba.privacy_app, tv6pbVMQFF (privacy-choice UIs — user-facing)
  com.samsung.tv.coba.adagent (Vetro Smart Hub dependency guard, not present here but kept)

| # | app_id | purpose | current onboot/autorestart | disable command | undo command |
|---|---|---|---|---|---|
| 1 | adplatform.ADPlayer | Advertising player. | (see package_app_info) | `pkgcmd -D -t app -n adplatform.ADPlayer --uid 5001` | `pkgcmd -A -t app -n adplatform.ADPlayer --uid 5001` |
| 2 | com.samsung.tizen.samsung-analytics | Collects and uploads Samsung usage analytics. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tizen.samsung-analytics --uid 5001` | `pkgcmd -A -t app -n com.samsung.tizen.samsung-analytics --uid 5001` |
| 3 | com.samsung.tv.ad-web-framework | Shows web-based advertising, for example in Samsung TV Plus. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.ad-web-framework --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.ad-web-framework --uid 5001` |
| 4 | com.samsung.tv.adplayer | Advertising player. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.adplayer --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.adplayer --uid 5001` |
| 5 | com.samsung.tv.canalysis-service | Content analysis daemon used by viewing-information services. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.canalysis-service --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.canalysis-service --uid 5001` |
| 6 | com.samsung.tv.cis-api-service-app | API service for content information (ACR). | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.cis-api-service-app --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.cis-api-service-app --uid 5001` |
| 7 | com.samsung.tv.contents-recognition-dbmgr | Database for on-screen content recognition. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.contents-recognition-dbmgr --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.contents-recognition-dbmgr --uid 5001` |
| 8 | com.samsung.tv.nvision-analysis-dbmgr | Model manager for on-screen image analysis. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.nvision-analysis-dbmgr --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.nvision-analysis-dbmgr --uid 5001` |
| 9 | com.samsung.tv.pisa-service | Personalised content and advertising service for Smart Hub. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.pisa-service --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.pisa-service --uid 5001` |
| 10 | com.samsung.tv.targeted-ad-service | Selects targeted advertising. | (see package_app_info) | `pkgcmd -D -t app -n com.samsung.tv.targeted-ad-service --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.targeted-ad-service --uid 5001` |
| 11 | content-grab-service | Captures frames of the current picture for content services. | (see package_app_info) | `pkgcmd -D -t app -n content-grab-service --uid 5001` | `pkgcmd -A -t app -n content-grab-service --uid 5001` |

## Apply protocol (when approved — not yet executed)

1. One package at a time; run disable, then read back:
   sqlite3 package_info.package_disable / package_app_info state for that app;
   ps check: no new/lingering process of that name.
2. Record undo line BEFORE the disable (table above).
3. After each package: root channel still answers (id -u = 0).
4. Stop at the first unexpected result; undo that package.
5. Full pass ends with: payload health check + a reboot (channel must
   return on its own), then re-run this plan file as a diff of states.

Note: none of these 13 services was running at idle (ps, 2026-10-27) —
they are demand-started; targeted-ad-service carries app_onboot=true,
so the practical effect to verify after disabling is boot-time, not CPU.

## Batch 2 — commercial/unused (30 of 33; 3 coupled skipped)

Hotel/EP/factory components on a home set. Coupling check against the
keep set: 30 reference nothing we keep. Skipped as coupled: `org.tizen.ep-hotel-channel` (referenced by function-osd), `org.tizen.ep-hotel-factory` (referenced by tv-viewer/homesetting/broadcastingmenu/swu/...), `org.tizen.factory` (referenced by tv-viewer/ug-hbbtv-efl).

| # | app_id | purpose | disable | undo |
|---|---|---|---|---|
| 1 | com.samsung.ep-plateau-agent | com.samsung.ep-plateau-agent | `pkgcmd -D -t app -n com.samsung.ep-plateau-agent --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep-plateau-agent --uid 5001` |
| 2 | com.samsung.ep-plateau-agent-service | com.samsung.ep-plateau-agent-service | `pkgcmd -D -t app -n com.samsung.ep-plateau-agent-service --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep-plateau-agent-service --uid 5001` |
| 3 | com.samsung.ep-plateau-info | com.samsung.ep-plateau-info | `pkgcmd -D -t app -n com.samsung.ep-plateau-info --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep-plateau-info --uid 5001` |
| 4 | com.samsung.ep-tbmapp-launcher | com.samsung.ep-tbmapp-launcher | `pkgcmd -D -t app -n com.samsung.ep-tbmapp-launcher --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep-tbmapp-launcher --uid 5001` |
| 5 | com.samsung.ep.coba.hotel | CoBA Hotel Component | `pkgcmd -D -t app -n com.samsung.ep.coba.hotel --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep.coba.hotel --uid 5001` |
| 6 | com.samsung.ep.hotel-popup | com.samsung.ep.hotel-popup | `pkgcmd -D -t app -n com.samsung.ep.hotel-popup --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep.hotel-popup --uid 5001` |
| 7 | com.samsung.ep.hotel-quicksetting-editor | com.samsung.ep.hotel-quicksetting-editor | `pkgcmd -D -t app -n com.samsung.ep.hotel-quicksetting-editor --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep.hotel-quicksetting-editor --uid 5001` |
| 8 | com.samsung.ep.hotel.uigadgets | com.samsung.ep.hotel.uigadgets | `pkgcmd -D -t app -n com.samsung.ep.hotel.uigadgets --uid 5001` | `pkgcmd -A -t app -n com.samsung.ep.hotel.uigadgets --uid 5001` |
| 9 | com.samsung.hitcomp | hitcomp | `pkgcmd -D -t app -n com.samsung.hitcomp --uid 5001` | `pkgcmd -A -t app -n com.samsung.hitcomp --uid 5001` |
| 10 | com.samsung.tv.coba.plateauhome | com.samsung.tv.coba.plateauhome | `pkgcmd -D -t app -n com.samsung.tv.coba.plateauhome --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.coba.plateauhome --uid 5001` |
| 11 | com.samsung.tv.demo-player | com.samsung.tv.demo-player | `pkgcmd -D -t app -n com.samsung.tv.demo-player --uid 5001` | `pkgcmd -A -t app -n com.samsung.tv.demo-player --uid 5001` |
| 12 | ep-hotel-protocol | ep-hotel-protocol | `pkgcmd -D -t app -n ep-hotel-protocol --uid 5001` | `pkgcmd -A -t app -n ep-hotel-protocol --uid 5001` |
| 13 | ep-log-manager | ep-log-manager | `pkgcmd -D -t app -n ep-log-manager --uid 5001` | `pkgcmd -A -t app -n ep-log-manager --uid 5001` |
| 14 | org.tizen.AgingApp | AgingApp | `pkgcmd -D -t app -n org.tizen.AgingApp --uid 5001` | `pkgcmd -A -t app -n org.tizen.AgingApp --uid 5001` |
| 15 | org.tizen.UsbSyncDisplay | UsbSyncDisplay | `pkgcmd -D -t app -n org.tizen.UsbSyncDisplay --uid 5001` | `pkgcmd -A -t app -n org.tizen.UsbSyncDisplay --uid 5001` |
| 16 | org.tizen.automation-alert | automation-alert | `pkgcmd -D -t app -n org.tizen.automation-alert --uid 5001` | `pkgcmd -A -t app -n org.tizen.automation-alert --uid 5001` |
| 17 | org.tizen.automation-app | automation-app | `pkgcmd -D -t app -n org.tizen.automation-app --uid 5001` | `pkgcmd -A -t app -n org.tizen.automation-app --uid 5001` |
| 18 | org.tizen.automation-viewer | automation-viewer | `pkgcmd -D -t app -n org.tizen.automation-viewer --uid 5001` | `pkgcmd -A -t app -n org.tizen.automation-viewer --uid 5001` |
| 19 | org.tizen.cloning | cloning | `pkgcmd -D -t app -n org.tizen.cloning --uid 5001` | `pkgcmd -A -t app -n org.tizen.cloning --uid 5001` |
| 20 | org.tizen.ep-hotel-alarm | EP Hotel Alarm | `pkgcmd -D -t app -n org.tizen.ep-hotel-alarm --uid 5001` | `pkgcmd -A -t app -n org.tizen.ep-hotel-alarm --uid 5001` |
| 21 | org.tizen.ep-hotel-channellist | Channel-list Application | `pkgcmd -D -t app -n org.tizen.ep-hotel-channellist --uid 5001` | `pkgcmd -A -t app -n org.tizen.ep-hotel-channellist --uid 5001` |
| 22 | org.tizen.ep-hotel-popup-ui | ep-hotel-popup-ui | `pkgcmd -D -t app -n org.tizen.ep-hotel-popup-ui --uid 5001` | `pkgcmd -A -t app -n org.tizen.ep-hotel-popup-ui --uid 5001` |
| 23 | org.tizen.ep-hotel-protocolui | ephotel-protocolui | `pkgcmd -D -t app -n org.tizen.ep-hotel-protocolui --uid 5001` | `pkgcmd -A -t app -n org.tizen.ep-hotel-protocolui --uid 5001` |
| 24 | org.tizen.ep-hotel-security | ep-hotel-security | `pkgcmd -D -t app -n org.tizen.ep-hotel-security --uid 5001` | `pkgcmd -A -t app -n org.tizen.ep-hotel-security --uid 5001` |
| 25 | org.tizen.ep-system-manager | ep-system-manager | `pkgcmd -D -t app -n org.tizen.ep-system-manager --uid 5001` | `pkgcmd -A -t app -n org.tizen.ep-system-manager --uid 5001` |
| 26 | org.tizen.ephotel-cloning | hotelcloning | `pkgcmd -D -t app -n org.tizen.ephotel-cloning --uid 5001` | `pkgcmd -A -t app -n org.tizen.ephotel-cloning --uid 5001` |
| 27 | org.tizen.factory-analysis-viewer | org.tizen.factory-analysis-viewer | `pkgcmd -D -t app -n org.tizen.factory-analysis-viewer --uid 5001` | `pkgcmd -A -t app -n org.tizen.factory-analysis-viewer --uid 5001` |
| 28 | org.tizen.remote-service-logging-debug-menu | Remote Service Debug Menu | `pkgcmd -D -t app -n org.tizen.remote-service-logging-debug-menu --uid 5001` | `pkgcmd -A -t app -n org.tizen.remote-service-logging-debug-menu --uid 5001` |
| 29 | org.tizen.rscm-screensaver | Remote Shop Content Management | `pkgcmd -D -t app -n org.tizen.rscm-screensaver --uid 5001` | `pkgcmd -A -t app -n org.tizen.rscm-screensaver --uid 5001` |
| 30 | org.tizen.widget_viewer_sdk | Widget Viewer for SDK | `pkgcmd -D -t app -n org.tizen.widget_viewer_sdk --uid 5001` | `pkgcmd -A -t app -n org.tizen.widget_viewer_sdk --uid 5001` |

## Batch 3 — optional menu (awaiting owner selection)

Nothing here is pre-planned: these are user-facing features. The full
menu with purposes and reverse-dependencies is in
`docs/debloat/qnx1d-optional-menu.md`. Area defaults proposed:

- **voice** — disable ONLY if the voice remote/mic features are never used (23 pkgs; kills Bixby/Alexa/wakeup engines; the remote mic button stops working)
- **ambient** — safe to disable on a non-Art-Mode household (14 pkgs)
- **sharing** — disable only if Multi View/AirPlay/mirroring are never used (21 pkgs)
- **devices** — CAUTION: includes Bluetooth framework pieces — a BT remote/audio dies with it (32 pkgs; pick individually)
- **samsung** — disable only if Samsung account/SmartThings/store billing are never used (32 pkgs)
- **support** — mostly remote-diagnostics; moderate (13 pkgs)
- **media** — CAUTION: includes store/streaming apps you may want (25 pkgs; pick individually)

Mark the areas (or individual app_ids) and they are appended to the plan
with per-package commands exactly like batch 1/2.
