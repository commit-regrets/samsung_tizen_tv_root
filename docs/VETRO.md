# Vetro on the QNX1D — install and test record (2026-11-05)

This records the first successful Vetro install on this TV, what it uses, and
what is still blocked. It is deliberately separate from `HANDOFF.md`: the
shared docs were being edited concurrently.

## Current state

| Item | Value |
|---|---|
| TV | QNX1D (`<MODEL>`), Tizen 9.0 |
| Vetro | **0.3.5**, package `vetrotvapp`, app id `vetrotvapp.app` |
| Certificate | **Partner**, valid 2026-11-05 → 2027-11-05, covers this TV's DUID |
| Vetro dashboard | `http://<TV_IP>:8099/` |
| Root agent | **disconnected at the time of writing**; it was connected as `uid=0`, `cap_eff=0000003fffffffff`, mode `tv-integration` while Host PC IP was `127.0.0.1` |
| Developer Mode Host PC IP | **`<PC_IP>`** at the time of writing, required to install/arm TV-Store; **`127.0.0.1` is required for Vetro's root agent** |
| TV-Store | **installed** (`A2STVStore`, 0.3.18) and armed with the Public certificate; relay mode wants Host PC IP = the TV's own LAN address |
| Vetro remote input | **disabled** (`enabled=false`, `connected=false`) |
| Our `remote/` daemon | **inactive**, config `mode=observe` |
| APL Launcher | **uninstalled 2026-11-05** at the owner's request; package `APLauncher` removed, install path kept below for reference |
| Root channel 31337 | works independently; Vetro does not use it |

Vetro's TV screen is a diagnostic page. It can sit on “Checking” for up to
about two minutes because it runs 11 probes sequentially, including a 25-second
service-reach check plus report/screen timeouts. The authoritative state is
`/status` and `/screen`, not the TV screen.

## Install from a TV rooted with our payload — step by step

Our root is only the starting point. Vetro still uses its own SDB root agent;
do not expect Vetro to call 31337.

### Prerequisites

- The TV is already rooted by our payload:
  `python tools/root_shell.py "id" <TV_IP>` returns `0`.
- The PC and TV are on the same trusted LAN.
- Apps2Samsung CLI or the desktop app is installed on the PC.
- A Samsung account is available for the certificate sign-in.

### 1. Enable Developer Mode and point it at the PC

On the TV:

1. Open **Apps**.
2. Type **12345**.
3. Turn **Developer Mode ON**.
4. Set **Host PC IP** to the PC's LAN address (`<PC_IP>`).
5. **Restart the TV** — a PC reboot is not enough.

Verify from the PC:

```text
apps2samsung-cli tv <TV_IP>
```

It must say `developer mode on, host <PC_IP>`. If it says Developer Mode off or
shows another host, fix the TV setting and restart the TV before continuing.

### 2. Create the certificates

```text
apps2samsung-cli cert --prepare --tv <TV_IP>
```

This creates a **Public** certificate for the TV's DUID. A Samsung sign-in page
opens; sign in there. Do not paste the password into this chat.

The Vetro install below will request **Partner** signing, which needs a second
Samsung sign-in for the same DUID. Both certificates are stored on the PC, tied
to that TV.

### 3. Install Vetro

```text
apps2samsung-cli install "Vetro" --tv <TV_IP> --allow-root --yes
```

- Apps2Samsung downloads the catalog `Vetro.wgt` (0.3.5 at the time of this
  record), re-signs it with the Partner certificate, and installs it over SDB.
- `--allow-root` is required; Vetro is a root-integration package.
- If it stops at a warning, read it before adding `--yes`.
- The install must happen while Host PC IP is the **PC's LAN address**, not
  `127.0.0.1`.

### 4. Switch to TV-local SDB for Vetro's root agent

On the TV:

1. **Apps → 12345 → Developer Mode**.
2. Set **Host PC IP** to **`127.0.0.1`**.
3. **Restart the TV**.

This makes the TV talk to its own SDB service, which is what starts Vetro's root
helper. The PC loses SDB access to the TV at this point — expected.

Wait up to 90 seconds, then open:

```text
http://<TV_IP>:8099/status
```

Required result:

```json
"mode": "tv-integration",
"agent": { "connected": true, "uid": 0 }
```

The TV screen may say “Checking” for up to about two minutes; `/status` is the
authoritative check. If the agent stays disconnected, verify Host PC IP is
`127.0.0.1`, the TV was restarted, and the install used `--allow-root`.

### 5. Installing anything else later

While Host PC IP is `127.0.0.1`, the PC cannot use SDB, so Apps2Samsung CLI
installs fail. To install another package:

1. Set Host PC IP back to `<PC_IP>` and restart the TV.
2. Install the package with Apps2Samsung.
3. Set Host PC IP to `127.0.0.1` and restart again for Vetro.

### 6. TV-Store (optional relay)

TV-Store is a separate Apps2Samsung app (`A2STVStore.Store`, catalog version
0.3.18), not Samsung's `com.samsung.tv.store` “Apps”.

- Install it while Host PC IP is `<PC_IP>`:
  `apps2samsung-cli install "TV-Store" --tv <TV_IP> --yes`.
- Open TV-Store once and enable **Connect from Apps2Samsung**.
- Arm it with the certificate:
  `apps2samsung-cli tvstore --tv <TV_IP>`.
- The relay wants Host PC IP set to the **TV's own LAN address**
  (`<TV_IP>`), while Vetro wants `127.0.0.1`. Those are different modes; only
  one can be active at a time.

Do not expect TV-Store and Vetro's root agent to both work with the same
Developer Mode host setting.

### 7. Verify and recover

```text
# root channel is independent of SDB
python tools/root_shell.py "id" <TV_IP>          # 0

# Vetro
http://<TV_IP>:8099/status
http://<TV_IP>:8099/screen
```

- To uninstall Vetro: use Apps2Samsung while Host PC IP points at the PC.
- To stop Vetro's root agent: set Host PC IP away from `127.0.0.1` and restart.
- Keep the Partner certificate private; it is tied to the TV's DUID.
- The Vetro dashboard is plain HTTP with no login: trusted LAN only.

## Why it failed before and worked now

Earlier attempts had **no signing certificate**. Vetro is marked **root** and
requires a **Partner-level** certificate:

1. Apps2Samsung created a Public certificate for the TV DUID.
2. The Vetro install requested Partner signing; a second Samsung sign-in created
   the Partner certificate for the same DUID.
3. Apps2Samsung downloaded `Vetro.wgt` 0.3.5, re-signed it with the Partner
   certificate, and installed it over SDB while Host PC IP pointed at the PC.
4. After install, Host PC IP was set to `127.0.0.1` and the TV was restarted.
   The root agent connected.

Commands used on the PC (Apps2Samsung CLI 3.1.0):

```text
apps2samsung-cli tv <TV_IP>
apps2samsung-cli cert --prepare --tv <TV_IP>
apps2samsung-cli install "Vetro" --tv <TV_IP> --allow-root --yes
```

Then on the TV: Apps → 12345 → Developer Mode → Host PC IP `127.0.0.1` →
restart. Wait up to 90 seconds, then check `/status`.

## What Vetro actually uses

Vetro does **not** use our 31337 root channel or the MultiControl payload:

```text
Vetro UI
  └─ Vetro Node service
       └─ TV-local SDB (127.0.0.1:26101)
            └─ appinstall tpk
                 └─ SamsungTvRootAgent.dll → uid=0
```

The SDB loopback setting is what lets the TV start its own root helper. While it
is set, a PC cannot use SDB on this TV. Our 31337 channel is independent and
kept working through this change.

This means Vetro is “on a TV that our root also roots”, not “using our root”.
A Vetro fork could route its `agentExecute` through 31337, but that requires
patching `rooting/service/platform.js`, rebuilding/re-signing the WGT, and
maintaining the patch across updates.

## Evidence

`GET /status`:

```json
"mode": "tv-integration",
"agent": {
  "connected": true,
  "uid": 0,
  "cap_eff": "0000003fffffffff",
  "smack": "User"
},
"attempts": [
  { "phase": "launch", "connect": "ok" },
  { "phase": "agent-connected", "output": "uid=0 cap=0000003fffffffff" }
]
```

`GET /screen`:

```json
"root": { "mode": "tv-integration", "connected": true },
"launcher": { "installed": true, "enabled": false },
"input": { "enabled": false, "connected": false },
"memory": { "availableMb": 485 }
```

## APL Launcher — installed, then removed

APL full WGT **v1.0.16** was installed as `APLauncher.Home` and then **uninstalled
on 2026-11-05 at the owner's request**. Home stayed on Samsung's
`com.samsung.tv.csfs` throughout; the APL app never took over the Home role.
The successful install path is kept for a future reinstall.

The Apps2Samsung CLI **does re-sign a local `.wgt`** with this TV's Partner
certificate:

```text
apps2samsung-cli install <path>\apl-launcher-full-v1.0.16.wgt --tv <TV_IP> --yes
```

That install ran while Developer Mode's Host PC IP was the PC's LAN address and
completed at 100%; the app was launched with `app_launcher -s APLauncher.Home`.

Two failed paths, for the record:

- `pkgcmd -i -t wgt -p` directly over 31337 failed with
  `-12 Invalid certificate chain`: the release WGT is signed by the upstream
  author, and `pkgcmd` does not re-sign.
- TV-Store upload (`PUT /upload?name=...` on port 8077) accepted the package and
  signed it, but signed with the **Public** certificate, then handed it to the
  TV's `wascmd` and never completed. TV-Store is optional and not needed for
  APL.

After an APL reinstall, configure it before relying on Home/remote:

1. Set Host PC IP to `127.0.0.1`, restart, and confirm Vetro's agent is
   connected (`/status`).
2. Open APL Launcher once.
3. In Vetro's **Remapper**, use `Smart Control 2016` if the remote is paired over
   Bluetooth. Map **Home** to **APL Launcher** (`APLauncher.Home`), save, enable
   **Remote interception**, and turn Vetro's own Launcher (Beta) off.
4. Click **Done — set up the buttons** in APL. It moves Home to **APL Overlay**
   (`APLauncher.Overlay`) and adds ⏯ for the Control Center.
5. APL Overlay is hidden from Vetro's app list (no icon). If it is not offered,
   add it from the Vetro Remapper page's browser console:
   `document.getElementById('targetApp').add(new Option('APL Overlay', 'APLauncher.Overlay'))`
   then select it.
6. For start-on-boot, use APL's **Settings › General & Privacy › Start on APL
   Launcher** (needs Vetro), or the TV's Autorun settings described in APL's
   installation guide.

## Security / operational notes

- The Vetro dashboard is plain HTTP with no login; keep it on a trusted LAN.
- The Vetro root agent is UID 0 with full capabilities.
- The Partner certificate is tied to this TV's DUID; keep the certificate store
  private (`%APPDATA%\Apps2Samsung\Certificate` on this PC).
- Do not run Vetro's remapper and our `remote/` daemon at the same time; two
  `EVIOCGRAB` clients conflict. Ours is currently stopped.
- Vetro's “Checking” screen is cosmetic; `/status` is the truth.
- Vetro's root route is SDB-dependent. Our payload root is independent and is
  the recovery path if SDB/Developer Mode is unavailable.

## Restore / recovery

- To use Apps2Samsung or PC SDB again: set Host PC IP back to the PC address,
  restart, install, then set `127.0.0.1` again for Vetro's agent.
- To stop Vetro's root agent: change Host PC IP away from `127.0.0.1` and
  restart; the agent cannot launch without TV-local SDB.
- To uninstall Vetro: use Apps2Samsung while Host PC IP points at the PC, or the
  TV's app manager.
- Our root channel remains on 31337 regardless of the SDB setting.

## Next steps

1. APL was uninstalled; no APL/Overlay remapper setup is active. Vetro alone is
   installed, with its remote input still off.
2. If APL is reinstalled, set Host PC IP to `127.0.0.1`, restart, and configure
   APL Launcher/Overlay in Vetro's Remapper (Home → APL Overlay, remote
   interception on).
3. Test a cold boot with the PC off and verify Vetro returns.
4. Keep the custom `control-center/` as a no-Vetro fallback; do not enable both
   remote remappers at once.
5. Re-run a cold-boot check after enabling remote input and after any Host PC IP
   toggle.
