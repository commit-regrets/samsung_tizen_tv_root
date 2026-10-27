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
