# HANDOFF — 2026-11-01, after the v45 deploy and cold-boot acceptance

Written so the next agent (or human) can pick this up without re-deriving the
session. Read this first, then `AGENTS.md` §0–§1, then
[`OPEN-ISSUES.md`](OPEN-ISSUES.md) — that file is the prioritised work list.
The current artifact md5/size live only in the generated state row in
`AGENTS.md` §1; do not copy numbers into prose.

## Where it stands right now

- **Repo:** branch `develop`, clean working tree; the offline suite
  (`python tools/test_all.py`) is **16/16**.
- **TV:** on **v45** (the artifact in `server/payload.dll`), rooted at boot;
  uid 0 with full caps, the standing debloat set applied (app rows + unit
  masks), boot row present, easysetup-daemon active and not looping.
- **PC server:** `pysrv.exe` on :80; the beacon-token set is persisted in
  `server/logs/beacon-tokens.json` and reloaded on start, so a PC restart no
  longer orphans the deployed payload.
- **Boot numbers (v45, 2026-11-01 16:15, mains cycle):** attempt 1
  `fast-exit` (allocation lottery) → attempt 2 `tag=exact` + `direct-patch
  uid=0` at 37 s → channel at 38 s → masks verified at 44 s. No `long-exit`
  line: the v45 gate was inert, as designed, on a normal boot.
- **Rollback:** stock IL is still in `mcs_orig.dll`; `payload_backup.dll` is the
  v44 artifact (the deploy that followed it saved v44 for us).

Session history and *why* each change exists: `CHANGELOG.md` (three entries,
2026-11-01). Do not re-litigate decisions recorded there without reading them.

## Done in this session (committed)

1. **Review fixes across the 2026-10-31 tree** — debloat scripts' silent-success
   paths, `deploy.sh` 0644 host/allow files, `uninstall.sh` label prelude,
   `server.py` `.pyc`/`__pycache__` leak + absolute request deadline + token
   trimming + dangling `tv_sock` + stale RPC waiter, and the Python lane's
   sane-cred gate, cred-scan desync/budget, readmany bounds and the
   `smack_relabel` PA/VA mix.
2. **An honest post-deploy gate** — `root.ps1` no longer accepts a bare TCP
   probe as "payload active". It runs `tools/wait_rooted.py`, which waits for
   the old listener to drop and for `id -u` = 0 (exit 3 = rooted but the port
   never dropped, i.e. the previous DLL may still be running).
3. **Deploy attempt-budget reset** — `deploy.sh` removes `/tmp/.dsh_try`
   before its restart, so a deploy after a bad boot gets a fresh fast budget.
4. **`BLIND-WALK`** — `tools/beacons.py` derives it for a long-mode pass that
   never saw a landmark, with a power-cycle hint naming the version boundary.
5. **v45 payload** — a rootless LONG-mode pass now exits for a fresh process
   (release device + landmark children first, cap 3 per boot via
   `/tmp/.dsh_long`, beacon `long-exit attempt=N count=K`). Deployed and
   cold-boot accepted; `LONG-EXIT` is decoded by the analyzer.
6. **New offline layers** — `tools/test_server_unit.py`,
   `tools/test_hygiene.py`, `tools/test_wait_rooted.py`; the analyzer fixtures
   grew the v45 boot shape and the deploy-script `dsh_try` case.

## Pending — ordered, with what each needs and how to prove it

| # | Item | Needs | Proof |
|---|---|---|---|
| 1 | **Live-stub layer** — the only layer still SKIPped on this PC | TV browser opened on `http://<pc>/index.html`, wait for `RUNNING`, keep it open | `python tools/test_all.py --tv` ends with the live-stub layer OK (protocol, kernel read, oversize READ/WRITE refused, stub alive) |
| 2 | **`deploy.sh` prints `RESTART_KILL=` / `RESTART_START=` into a detached subshell whose stdout is `/dev/null`** — "old app never died, new DLL not loaded" still passes the `id -u` gate | payload change, deploy, boot | payload beacons its own artifact md5 at start (proposal in `docs/V45-BLIND-WALK.md`), so a stale process is provable; script side can be tested offline |
| 3 | **`mask.sh` lists units without `--full`** — a very long unit name could be ellipsized in the 80-column dump | one TV query | compare `systemctl list-units --no-legend` name widths against the committed list; if any is clipped, add `--full` in `mask.sh` and the payload's mask check |
| 4 | **`mask.sh` counts a failed stop but not a unit that stays `active` after its stop exited 0** | TV | add an `is-active` pass over the units counted `stopped`; offline test with the stubbed `systemctl`, then one live run |
| 5 | **`HEAD` answers with a body; `OPTIONS` is served as `GET`** | nothing (offline) | a case in `tools/test_server_unit.py`; low value unless a client starts using them |
| 6 | **Beacon tokens are self-service** | none — *by design*; the LAN is the boundary | revisit only if the server is exposed beyond the LAN (`SECURITY.md`) |
| 7 | **High-half read mechanism** — one deliberate high-PA read; re-read the v38 `high-scan` verdicts against `high_memory` = `0xF0400000` | TV + browser lane | record the verdict in `OPEN-ISSUES.md` → Pending; no boot-path change |
| 8 | **Portability** — no second model/firmware tested | a second TV | the four gates and the file-by-file checklist in `PORTABILITY.md`; record each unit there |
| 9 | **Debloat tier 2b (Control Center layer)** | owner decision + measurements | next moves are listed in `debloat/AGENTS.md` |
| 10 | **Opportunistic: watch `long-exit` fire for real** — the branch is offline-tested only; the acceptance boot never needed it | a deploy restart that lands in the stale window | expect `long-exit attempt=N count=1` then a relaunch instead of a multi-minute hunt; capture the log and add it to `CHANGELOG.md` + `AGENTS.md` §7 |

Nothing in the list blocks day-to-day use: the TV roots on every cold boot, the
masks come back on their own, and a deploy is verified with `id -u` = 0.

## First commands for the next agent

```sh
cd <this repo>
git log --oneline -5                  # where the session ended
python tools/test_all.py              # 16 offline layers
python tools/update_state.py --check  # §1 state row vs artifacts/state.json
python tools/sanitize_for_public.py --check

python tools/beacons.py               # per-boot verdicts; --json for machines
python tools/root_shell.py "id -u" <tv-ip>
python tools/root_shell.py \
  "grep -E '^CapEff' /proc/self/status; md5sum /opt/usr/apps/com.samsung.tv.MultiControl-Service/bin/MultiControlService.dll" <tv-ip>
```

The TV address is not baked into anything: read it from
`server/logs/beacons.log` (`ROOTCHAN … bind=`) or from `rootchan.host`, or ask
the owner.

## Rules and traps that cost hours (short version)

- **Every change needs a `CHANGELOG.md` entry**, including a doc or script
  behaviour change. The §1 state row is generated: edit `docs/state.json`, then
  `python tools/update_state.py --fix`.
- **Never paste the live beacon token** (or a full LAN IP/model string) into
  prose; `tools/sanitize_for_public.py --check` must stay green.
- `.sh`/`.py` are LF-only (`.gitattributes` pins them); a CR breaks the TV's
  busybox `sh`.
- **Do not raise the fast-attempt count** (`/tmp/.dsh_try`, currently 4). The
  v31 regression (boot 132 s) is why. Only a *fresh process* re-rolls a stale
  mapping; that is what fast-exit and v45's long-exit encode.
- **A deploy restart can land in the stale window.** With v45 the payload now
  exits and re-rolls up to 3 times; after that it idles and the recovery is a
  mains power-cycle (ask the owner — the remote's power button is only standby).
- **Do not `systemctl --force reboot`** from the payload (trap 12), **do not
  touch `/mnt/systemrw`** (trap 9), and keep auto-update off.
- The physmap node is exclusive: the payload must stay on `/dev/video40` and
  only advance on `ENOENT`/`ENODEV`; a busy video40 is retried, never cycled.
- `root.ps1 -Force` is the redeploy path; it rotates the beacon token (expected,
  saved automatically) and only reports success on `id -u` = 0.

Deeper: `AGENTS.md` §8 (all 18 traps) and `docs/FAILED.md` (dead ends to
repeat at your peril).

## Where things live

| Question | File |
|---|---|
| State now, procedures, traps | `AGENTS.md` §1, §6–§9 |
| Prioritised work list | `docs/OPEN-ISSUES.md` |
| Every beacon / tool error decoded | `docs/LOGGUIDE.md` |
| How the chain works | `docs/EXPLOIT.md`, `docs/ROOT-METHODS.md` |
| Dead ends (do not retry) | `docs/FAILED.md` |
| Tests and what each layer proves | `docs/TESTING.md` |
| PC server hosting, tokens, hardening | `docs/SERVER-HOSTING.md`, `SECURITY.md` |
| v45 rationale + acceptance | `docs/V45-BLIND-WALK.md` |
| Debloat subtree state | `debloat/AGENTS.md` |
| Dated history (what changed and why) | `CHANGELOG.md` |
