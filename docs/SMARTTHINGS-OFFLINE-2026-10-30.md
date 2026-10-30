# SmartThings shows the TV "offline" — resolved: `org.tizen.easysetup-daemon`

**Status: CLOSED.** Cause is `org.tizen.easysetup-daemon`. Restore confirmed: owner, phone **online** ~18:51 after the app was re-enabled and launched.

Owner-confirmed bisect, 0 masks throughout, analytics stayed enabled:

| Step | Disabled | Phone |
|---|---|---|
| fully stock | 0 | **online** ~18:32 |
| voice 22 | 22 | **online** ~18:35 |
| + tier 1 (10) | 32 | **online** ~18:37 |
| + tier 2a (6) | 38 | **offline** ~18:42 |
| those 6 re-enabled, thing pid unchanged | 32 | **online** ~18:44 |
| `org.tizen.easysetup-daemon` only | 33 | **offline** ~18:46 |
| re-enabled and launched (pid 7010) | 32 | **online** ~18:51 (owner) |

The thing respawn that accompanied the tier-2a disable was not the cause:
the phone returned to online on that same pid once the 6 were re-enabled.
The single following change, easysetup alone, flipped it offline again.
Its manifest carries `http://tizen.org/iot/metadata/master` and `.../resource`,
the same IoT roles `smartthings-thing` provides.

Locked: denylisted in `apply.sh`, dropped from `tier2a-tcc-apps.txt`, and
`org.tizen.easysetup-daemon.service` dropped from the mask list (masking the
unit would stop the same daemon). Re-enabled, launched, and the phone is
**online** again (owner, ~18:51). Voice 22 and tier 1 10 stay disabled; they
were online. The other five tier 2a ids stay in the disable list — they were
enabled during the online readings.

---

## 1. The question to answer

The owner's phone (Samsung SmartThings app) lists the TV as **"offline"**, so
phone control does not work. The TV itself is up: rooted, network fine, and its
SmartThings processes are running. **Find what makes the phone show offline, and
which debloat row is responsible.**

Non-goal: the root/debloat machinery itself works (root channel, payload v42,
`pkgcmd` disables, `/run` masks). Only the phone's view of the TV is broken.

---

## 2. Environment

| Thing | Value |
|---|---|
| TV | `<TV_IP>` (QNX1D, Tizen 9, rooted, uid 0) |
| Root channel | TCP 31337, line protocol, replies end `__END__` |
| PC | `<PC_IP>` (Wi-Fi); the phone is another LAN host |
| Repo | `C:\Users\Raghav\Documents\projects\samsung_tv_root` (branch `develop`) |
| TV-side debloat tools | `debloat/tools/{apply,restore,mask,unmask}.sh` |
| Debloat lists (source of truth) | `debloat/lists/*.txt` |
| Reference repos (owner suggested) | `C:\Users\Raghav\Documents\projects\samsungtv\tizen-tv-control-center`, `...\samsungtv\vetro` |

Run any TV command with:

```powershell
cd C:\Users\Raghav\Documents\projects\samsung_tv_root
$env:PATH = "C:\Program Files\Git\bin;" + $env:PATH   # for base64/sh helpers
python tools/root_shell.py '<one-line command>' <TV_IP>
```

Two hard quirks, both cost time tonight:

* **The channel is line-based: one command per call.** A multi-line command
  string executes only its first line. For several steps use `;` on one line or
  `cat /tmp/x.sh | sh -s <arg>` (UEP refuses `sh /tmp/x.sh` directly).
* **Quoting.** `sqlite3 ... "select ... where app_disable=char(116,114,117,101)"`
  works; single quotes inside the command string regularly break. Nested
  `$( ... case ... esac ... )` breaks too — keep command substitutions simple.

Useful reads:

```sh
sqlite3 /opt/dbspace/.pkgmgr_parser.db "select count(*) from package_app_info where app_disable=char(116,114,117,101)"
ls /run/systemd/system/*.service /run/systemd/system/*.socket 2>/dev/null | wc -l   # live masks
netstat -tlnp                                                                         # listeners + pids
netstat -tn | grep ESTABLISHED                                                        # cloud links
```

---

## 3. How to observe the symptom without the phone

The owner's phone is the only ground truth for "online", but these are the TV-side
signals that correlate:

| Signal | Online state | Offline state |
|---|---|---|
| `smartthings-client` process | running | (can be dead) |
| `smartthings-thing` process | running | (can be dead) |
| `stfind-daemon` | running | (can be dead) |
| cloud links (443/5229 to Samsung ranges) | several ESTABLISHED | fewer/none |

Find them:

```sh
for p in /proc/[0-9]*; do e=$(readlink $p/exe 2>/dev/null); case "$e" in *smartthings*|*stfind*) echo "pid=${p#/proc/} $(basename $e)";; esac; done
```

**But note:** the last observed state had **all three processes alive and five
cloud links up, and the phone still said offline** — so "stack alive" is
necessary but *not sufficient*. Do not treat it as the answer.

---

## 4. Facts learned the hard way (each verified tonight)

1. **There is no systemd unit for the SmartThings client.** It is launched by the
   app `com.samsung.tv.vd-sc-client-service` (see its `__AUL_CALLER_APPID__` in
   `/proc/<pid>/cmdline`). Nothing restarts it if it dies.
2. **`app_launcher -s com.samsung.tizen.smartthings-client` brings the whole stack
   back** (client + stfind + thing) in ~4 s. This is the no-reboot recovery and it
   is how the phone was restored the first time.
3. **Disabling a running SmartThings stack kills the client.** When the tier 2a
   batch (which contains `com.samsung.tizen.smartthings-thing` and
   `com.samsung.tv.mde-framework`) was applied with `pkgcmd -D` while the client
   was running, the client and thing agent died and stayed dead. Enabling the rows
   again does **not** restart them; you must `app_launcher -s` it or reboot.
4. **The phone status lags ~1–2 minutes.** Judging 20 s after a TV change
   produces misleading "offline" readings — several of tonight's conclusions were
   polluted by this.
5. **Inventory graph direction:** Vetro `usedBy` → inventory `referencedBy` means
   **who uses this package**. `smartthings-client.referencedBy` containing
   `com.samsung.tv.multiscreen` means *multiscreen uses the client*, not the
   reverse. `com.samsung.tv.mde-framework.referencedBy` contains
   `com.samsung.tizen.smartthings-thing`, i.e. *smartthings-thing uses
   mde-framework*. An earlier commit (`c09340d`) inverted this; it is corrected in
   `a78d3b5`.
6. **The inventory uses of the six non-stack tier 2a ids are unrelated to
   SmartThings**: `multi-assistant-service` = voice hub,
   `waapp-contents-provider` = wireless-audio content provider, `ambient*` =
   Ambient Mode, `easysetup-daemon` = first-run setup (used by
   `easysetup-mediator`).
7. The two reference repos contain **no** mention of the six tier 2a ids
   (`grep` over both trees returned nothing).

---

## 5. Timeline of live experiments (phone result per state)

| When | masks | app rows disabled | stack | Phone |
|---|---|---|---|---|
| 2026-10-30 15:54 | 34 | 58 (tier1+2a 20 + sharing 16 + voice 22) | running (boot-started) | reported dead, ~16:0x |
| 16:33 (boot) | 34 | 42 (sharing reverted) | boot-started | **offline** 16:43 |
| 17:05 | 0 (all started) | 4 (four refuse `-A`) | running | **online** ~17:25 |
| 17:28 | 30 | 42 | boot-started | offline 17:39 |
| 17:44 | 0 | 9 (tier 2a, incl. stack ids) | killed by the disable | offline |
| 17:52 | 0 | 6 | dead (no unit to restart) | offline |
| 17:57 | 0 | 6 | `app_launcher -s` → alive | offline (too early / lag) |
| ~18:00 | 0 | 0 (fully stock) | alive | **online** |
| 18:0x | 30 | 39 (tier1 11 + voice 22 + tier2a 6) | alive | **offline** |
| 18:1x | 0 | 39 | alive | **offline** |
| ~18:26 | 0 | 38 (analytics re-enabled) | restarted | **offline** (owner) |
| ~18:32 | 0 | **0** (all `-A`, incl. adplatform) | restarted | **online** (owner) |
| ~18:35 | 0 | 22 (voice only) | same pids | **online** (owner) — voice innocent |
| ~18:37 | 0 | 32 (voice 22 + tier 1 10) | same pids | **online** (owner) — tier 1 innocent |
| ~18:38 | 0 | 38 (+ tier 2a 6) | thing pid changed 28614→1777 | **offline** ~18:42 (owner) |
| ~18:44 | 0 | 32 (6 re-enabled, no restart) | thing still 1777 | **online** (owner) — respawn ruled out |

Interpretation (updated 18:44): the thing respawn was not the cause. The
phone came back with the same thing pid once the 6 were re-enabled. Next
single variable is `org.tizen.easysetup-daemon`.

---

## 6. Ruled out (do not re-investigate without new evidence)

| Hypothesis | Why it is dead |
|---|---|
| Batch 3's 16 sharing apps (multiscreen, AirPlay, d2d, remoteapp, …) | all re-enabled + rebooted → phone still dead (16:43) |
| `smartthings-client` / the `samsung` area being disabled | never in any list; row `false` throughout |
| The 4 phone-path units (`pushd`, `register-device`, `p2p-asm`) | all running in the failing states; the phone also failed with them up (18:0x); ~1.5 MB PSS anyway |
| `msf-server` (8001/8002) / `remote-server` (7678) being down | vendor boot services, up the whole time, owned by `/usr/bin`, no relation to our lists |
| The 6 non-stack tier 2a rows (inventory only) | inventory said no SmartThings user. Phone test says otherwise: adding them flipped online→offline (~18:42). Split in progress. |
| Masking `multiscreen.service` | it is not masked now; the app is enabled |
| Voice 22 (`batch3-optional.txt`) | disabled alone, stack pids unchanged, owner **online** ~18:35 |
| Tier 1 tracking, 10 remaining ids (analytics stays enabled) | added on top of voice, stack pids unchanged, owner **online** ~18:37 |
| Thing respawn | phone returned **online** on the same thing pid once the 6 were re-enabled (~18:44) |
| The other five tier 2a ids | enabled during both online readings (18:37 and 18:44) |

**Cause:** `org.tizen.easysetup-daemon`. Disabled alone on top of the online 32-row state → **offline** ~18:46. Re-enabled and launched (pid 7010) → **online** ~18:51 (owner). Denylisted; its unit is off the mask list.

---

## 7. Current live state

As of 2026-10-30 ~18:51 (owner: phone **online**):

* `org.tizen.easysetup-daemon` enabled and running (pid 7010).
* Disabled rows: **32** (voice 22 + tier 1 10). The five other tier 2a ids
  are enabled.
* masks: **0**. Policy files parked; the parked mask list does not name
  `org.tizen.easysetup-daemon.service`.
* Both directions are confirmed: disabling this app → offline, re-enabling
  it → online.

---

## 8. Rules that must not be broken

* **Never disable** `com.samsung.tizen.smartthings-thing`,
  `com.samsung.tv.mde-framework`, `com.samsung.tv.tvsensor-iot-service`,
  `com.samsung.tizen.smartthings-client`, `com.samsung.tv.smartthingsfind-daemon`,
  or `org.tizen.easysetup-daemon`
  — SmartThings phone control. All six are on the `apply.sh` denylist.
  Do not mask `org.tizen.easysetup-daemon.service` either.
* **Keep `pushd`, `register-device`, `p2p-asm` out of the mask list** (push
  channel, device registration, P2P session manager; ~1.5 MB PSS total).
* `pkgcmd -D` does **not** kill running instances; after disabling check for
  restart-looping units (trap 14a in `debloat/AGENTS.md`).
* Never write to `/mnt/systemrw`; never `systemctl --force reboot` from the
  payload (trap 9 / 12 in the root `AGENTS.md`).
* Keep `CHANGELOG.md`, `docs/state.json` and `debloat/AGENTS.md` updated with
  whatever you find. This issue is **solved** (see the header); do not leave
  the record as "cause unproven".

---

## 9. Files updated when this was solved (all done)

| File | What |
|---|---|
| `CHANGELOG.md` | the real cause, replacing the "cause unproven" entry |
| `docs/state.json` | then `python tools/update_state.py --fix` for the AGENTS §1 row |
| `debloat/AGENTS.md` | the never-disable rule + the mechanism |
| `debloat/lists/services-units.txt` | **29** units (drop the 4 phone-path units and `org.tizen.easysetup-daemon.service`) |
| `debloat/lists/services-bind.txt` | 23 binaries (drop `pushd`, `register-device`, `p2p-asm`) |
| `debloat/lists/tier2a-tcc-apps.txt` | **5** ids (drop the 3 stack ids and `org.tizen.easysetup-daemon`) |
| `tools/test_debloat.py` | locks: 29 units / 23 binaries / tier2a 5 ids, with the stack ids and easysetup asserted **absent** |

Run `python tools/test_all.py` and
`python tools/sanitize_for_public.py --check` before committing.

---

## 10. One-paragraph summary for a new reader

**Solved.** The cause is `org.tizen.easysetup-daemon`: disabling it alone
flips SmartThings from online to offline (owner-confirmed, one variable at a time,
0 masks throughout). It is denylisted, dropped from tier 2a, and its unit is off
the mask list - masking the unit stops the same daemon. Voice (22) and tier 1 (10)
stay disabled; the phone was online with those on. The final standing set is 37
app rows and 29 units. Along the way we also ruled out the sharing batch, the four
phone-facing services, `msf-server`/`remote-server`, `samsung-analytics` (a real
dependency, but not this cause) and the thing-agent respawn; the useful mechanism
notes are that disabling the SmartThings stack kills its client with no unit to
restart it (`app_launcher -s com.samsung.tizen.smartthings-client` recovers it)
and that the phone's status lags ~2 minutes.
