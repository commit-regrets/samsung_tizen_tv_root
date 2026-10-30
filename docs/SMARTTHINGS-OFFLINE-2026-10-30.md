# SmartThings shows the TV "offline" — open issue, handoff for a fresh agent

**Status: UNRESOLVED.** Written 2026-10-30 ~18:15 by the agent that spent the
evening on it. Read this top to bottom before touching the TV; the point of this
file is that you do not repeat the four wrong guesses listed in §6.

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
| 18:1x (current) | 0 | 39 | alive | **offline** (last reading, may be lag) |

Interpretation: online states are either *fully stock* or *almost fully stock*;
every configuration carrying a substantial debloat has read offline. The 30-mask
+ 39-row state read offline with the stack alive, which is why §7 starts from
"0 masks, 39 rows" rather than assuming the masks.

---

## 6. Ruled out (do not re-investigate without new evidence)

| Hypothesis | Why it is dead |
|---|---|
| Batch 3's 16 sharing apps (multiscreen, AirPlay, d2d, remoteapp, …) | all re-enabled + rebooted → phone still dead (16:43) |
| `smartthings-client` / the `samsung` area being disabled | never in any list; row `false` throughout |
| The 4 phone-path units (`pushd`, `register-device`, `p2p-asm`) | all running in the failing states; the phone also failed with them up (18:0x); ~1.5 MB PSS anyway |
| `msf-server` (8001/8002) / `remote-server` (7678) being down | vendor boot services, up the whole time, owned by `/usr/bin`, no relation to our lists |
| The 6 non-stack tier 2a rows (ambient×3, waapp-contents-provider, easysetup-daemon, multi-assistant-service) | disabled while the stack stayed alive (verified by process check); inventory shows no SmartThings user |
| Masking `multiscreen.service` | it is not masked now; the app is enabled |

Still **open**: the mask list as a set, and the tier 1 / voice app rows.

---

## 7. Current live state and where to start

At the time of writing:

* masks: **0** (`/opt/usr/data/debloat-masks.txt` holds the 30-unit list used
  earlier; `debloat-masks.txt.bak30` is the same file after renaming)
* app rows disabled: **39** = tier 1 (11) + voice (22) + tier 2a non-stack (6)
* policy files: present on `/opt/usr/data` (so a reboot re-applies 30 masks)
* SmartThings stack: client + thing + stfind **alive**, cloud links up

Suggested next step (the split that is not yet answered):

1. Confirm the current reading after **2 full minutes** (it may be lag from the
   masked state).
2. If still offline with **0 masks / 39 rows**, the app rows are the cause:
   re-enable them in two groups, checking after each (not faster than ~2 min):
   * tier 1's 11 (`debloat/lists/tier1-tracking.txt`),
   * voice's 22 (`debloat/lists/batch3-optional.txt`).
   Then bisect the guilty group by halves. Natural suspects by *name* are weak
   here: tier 1 is ads/analytics/ACR, voice is voice. If **both** groups come back
   online when re-enabled, the remaining suspect is the *last* group (tier 2a's 6)
   or the masks — go back to the mask list and bisect 30 → 15 → 8 …
3. If it comes back online when a group is re-enabled, bisect that group with
   `pkgcmd -D` / `-A` on single ids (the owner's phone needs ~2 min per check).

Every step is cheap on the TV; only the phone check is slow.

---

## 8. Rules that must not be broken

* **Never disable** `com.samsung.tizen.smartthings-thing`,
  `com.samsung.tv.mde-framework`, `com.samsung.tv.tvsensor-iot-service`,
  `com.samsung.tizen.smartthings-client`, `com.samsung.tv.smartthingsfind-daemon`
  — this is the SmartThings stack and the owner uses SmartThings. (Add them to the
  `apply.sh` denylist.)
* **Keep `pushd`, `register-device`, `p2p-asm` out of the mask list** (push
  channel, device registration, P2P session manager; ~1.5 MB PSS total).
* `pkgcmd -D` does **not** kill running instances; after disabling check for
  restart-looping units (trap 14a in `debloat/AGENTS.md`).
* Never write to `/mnt/systemrw`; never `systemctl --force reboot` from the
  payload (trap 9 / 12 in the root `AGENTS.md`).
* Keep `CHANGELOG.md`, `docs/state.json` and `debloat/AGENTS.md` updated with
  whatever you find — the current record says **cause unproven** and that is
  honest, not a placeholder.

---

## 9. Files that will need updating when this is solved

| File | What |
|---|---|
| `CHANGELOG.md` | the real cause, replacing the "cause unproven" entry |
| `docs/state.json` | then `python tools/update_state.py --fix` for the AGENTS §1 row |
| `debloat/AGENTS.md` | the never-disable rule + the mechanism |
| `debloat/lists/services-units.txt` | 30 units (drop the 4 phone-path units) if that is what survives |
| `debloat/lists/services-bind.txt` | 23 binaries (drop `pushd`, `register-device`, `p2p-asm`) |
| `debloat/lists/tier2a-tcc-apps.txt` | 6 ids (drop the 3 stack ids) |
| `tools/test_debloat.py` | locks: 30 units / 23 binaries / tier2a 6 ids incl. the stack ids asserted **absent** |

Run `python tools/test_all.py` and
`python tools/sanitize_for_public.py --check` before committing.

---

## 10. One-paragraph summary for a new reader

The TV is rooted and healthy; its SmartThings processes run and it holds cloud
connections, yet the owner's phone lists it "offline". Tonight we proved the
sharing-app batch and the four phone-facing services are innocent, that disabling
the SmartThings stack kills its client (recoverable with
`app_launcher -s com.samsung.tizen.smartthings-client` or a reboot), and that the
phone's status lags ~2 minutes. The remaining variable is the debloat payload
itself: with 39 app rows disabled and 0 masks the phone still reads offline, while
a fully-stock TV reads online. Bisect the app rows (tier 1 then voice) and then
the 30-unit mask list, with ≥2 minutes between a TV change and a phone judgement.
