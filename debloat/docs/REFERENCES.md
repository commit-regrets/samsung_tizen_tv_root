# References and how they compare

## tizen-tv-control-center — the primary reference (adopt)

GitHub slug `samsungtv/tizen-tv-control-center` — read from a local clone (no
canonical URL was recorded, so none is invented here) — built
on a Samsung **S90D OLED, EU, firmware T-PTMxxxx, Tizen 9, 2024** — the *same
firmware build family as the QNX1D unit this repo's inventory came from*.

Why it is the base for the apply layer, ahead of Vetro:

- **Same platform, same firmware string.** Its 41-app `pkgcmd -D` list
  (`tv/opt-etc/cc-disabled-apps.txt`) and its 33-program `parseinfo.sh`
  binary list are merge candidates for our inventory, not porting
  projects. The binary list became `lists/services-bind.txt` (kill list),
  but the *mechanism* it uses there — overlaying `/bin/true` via
  `parseinfo.sh` at boot — is only half applicable: at runtime it is
  falsified on our unit (19/25 respawned through the overlay; run log
  round 1), so service suppression here is `/run` masks. It independently
  confirms our disable mechanism. One correction this
  project contributed back: the "Failed to get appinfo" that tcc treats as
  a reason to avoid `--global` is what a REPEAT `--global` prints once the
  row is already true (exit 25) — `--global` is the persistent form
  (writes `package_app_info.app_disable`, cold-boot verified) and plain
  `pkgcmd -D` is the session-only one.
- **It consumes an external root** (no root method provided — by design),
  which is exactly this repo's contract. Its `tools/` wrap the root shell
  (`tvcmd.sh`, base64 chunked `push.sh`/`pull.sh` with md5 checks) and its
  `inventory.sh` is the same read-only dry-run discipline as our plan.
- **It solves the Tizen 9 layer neither Vetro nor cleanyourtv could**:
  Samsung Home replaced by a Control Center web app that survives reboots,
  the Picture-Clarity greyed-out fix, crash-loop elimination (voice-app
  relaunched 37x/40s on their unit — matches our AUL observations), native
  notification pop-ups.
- Tizen 9 facts identical to ours, independently measured: UEP blocks
  unsigned ELF and file-based scripts while inline `sh -c` and awk pass;
  SMACK labels govern app files; `/usr` and `/etc` are read-only; `dlog`
  disabled; `sdb push/pull` locked on retail.

Merge order for this repo: cross-check its 41-app list against
`models/qnx1d/qnx1d-inventory.json` and the denylist (note: their list
includes `MultiControl-Service` as a disable candidate — **our carrier,
hard-denied here**); its 33-program binary list is the kill list behind
our `/run` masks (the boot-time overlay it uses is not reproducible at
runtime here); reuse its `inventory.sh` checks per package.

## Vetro — classification data (done), dashboard maybe later

Already harvested: `models/qnx1d/qnx1d-inventory.json` is classified with Vetro
0.3.5's catalog (the vendored `app-catalog.js`/`app-facts.js` are byte-identical
to tag `v0.3.5`). Its own root route (TV-local SDB) does not apply here, and
its signed-WGT install needs a Developer Mode/certificate dance that our root
makes unnecessary. Its dashboard could still be driven by our root later
(option B); tcc's Control Center is the stronger candidate for that role.

## cleanyourtv — validation and list discipline (recorded)

Android-TV-only; its Samsung page (four sets) externally confirms no
ADB/shell on retail Tizen. List-file discipline adopted: one package per
line, validated bare names, restore from the same list.
