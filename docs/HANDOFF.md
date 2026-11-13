# HANDOFF — 2026-11-01, after the v46 deploy and its cold-boot acceptance

Written so the next agent (or human) can pick this up without re-deriving the
session. Read this first, then `AGENTS.md` §0–§1, then
[`OPEN-ISSUES.md`](OPEN-ISSUES.md) — that file is the prioritised work list.
The current artifact md5/size live only in the generated state row in
`AGENTS.md` §1; do not copy numbers into prose.

## Where it stands right now

- **Repo:** branch `develop`, **uncommitted working tree** (v46 + v46.1 below);
  the offline suite (`python tools/test_all.py`) is **17/17**.
- **TV:** on **v46** (the artifact in `server/payload.dll`), deployed 21:01 over
  the root channel and **cold-boot verified 21:10** (mains cycle); uid 0 with
  full caps, the standing debloat set applied (app rows + unit masks), boot row
  present, easysetup-daemon active and not looping.
- **PC server:** `pysrv.exe` on :80; the beacon-token set is persisted in
  `server/logs/beacon-tokens.json` and reloaded on start, so a PC restart no
  longer orphans the deployed payload.
- **Boot numbers:** **v46 cold boot 32 s** (2026-11-01 21:10: attempt 1
  `fast-exit` at t=18 s → attempt 2 launch t=29 s → `self-patch uid=0` t=32 s →
  channel 32 s → masks `loop-check=ok` t=39 s; both launches carried the deploy
  token + `art=c540a6ab…`). The v46 **deploy restart** rooted in 4 s, attempt 1
  (`direct-patch uid=0`), and `root.ps1` printed the two-witness `proven` line.
  Previous cold boot: v45, 16:15, attempt 2 at 37 s.
- **Rollback:** stock IL is still in `mcs_orig.dll`; `payload_backup.dll` is now
  the v45 artifact (`PREV_IL=35cc7577`).

Session history and *why* each change exists: `CHANGELOG.md` (eight entries,
2026-11-01). Do not re-litigate decisions recorded there without reading them.

## Done in this session (v46/v46.1 uncommitted; the rest committed)

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
7. **The stale-process proof (repo v46 + v46.1 — deployed 2026-11-01 21:01,
   cold-boot accepted 21:10)** — the
   payload reads the deploy-rendered artifact md5 from `rootchan.art` once at
   startup and appends `art=<md5>` to its start beacon, so `beacons.log` proves
   which DLL each process started with (a stale old process beaconed the
   PREVIOUS art). `deploy.sh` writes the md5 after the installed-file verify and
   before the restart, its restart subshell now logs
   `RESTART_KILL=`/`RESTART_START=` to `restart.log` instead of `/dev/null`, and
   `wait_rooted.py` reads that log back after a rooted answer. **v46.1**, after
   the second review: the launcher's proof now needs **both** the newest
   launch's `tok=` against the deploy's `TOKEN_FILE=` (freshness — redeploying
   identical bits leaves a survivor's `art=` matching) **and** its `art=`
   against `ART_FILE=` (identity); the "newest launch" rule is
   `tools/beacons.py --newest-start` (the v46 duplicate kept an older art when
   a newer launch had none), `wrc=3` exits 3 instead of claiming success, and
   the rollback removes `rootchan.art`/`restart.log` only when this attempt
   wrote them. The live proof landed with that deploy and boot (both fresh
   launches carried `tok=` + `art=`, and `root.ps1` printed `proven`). The beacon
   format was designed fresh in v46 — it was never a proposal in
   `docs/V45-BLIND-WALK.md`.

## Pending — ordered, with what each needs and how to prove it

| # | Item | Needs | Proof |
|---|---|---|---|
| 1 | **Live-stub layer** — **DONE 2026-11-01 23:56**: `test_stub.py` passed 7/7 (hello `PGDB`, kernel image readable, normal read, oversize READ/WRITE refused, stub alive) after a fresh browser launch. **Re-run 2026-11-05 on v48/73 rows: `test_all --tv --tv-ip` 19/19, stub-protocol and tv-health-live both OK.**  **The page must run in a renderer created AFTER the boot**, not the browser's preloaded first renderer: the first attempt (page loaded into the 21:55 preloaded renderer) aborted at `elf_base = 0xafaae350 [✗ invalid]`, while the fresh one found `0xafa4f000 [✓ ELF]`.  Quit the TV browser fully and reopen it before loading the page. | TV browser opened on `http://<pc>/index.html`, wait for `RUNNING`, keep it open | `python tools/test_all.py --tv --tv-ip <ip>` ends with `stub-protocol` and `tv-health-live` OK |
| 2 | **v47 payload (`list-units --full` in the mask check)** — **done 2026-11-02 00:11**: deployed 00:00 (two-witness `proven`), then a mains cycle — `direct-patch uid=0` t=40 s, `masks=29 stopped=29 killed=4 fail=0 missing=0 activating=1 listed-activating=0 loop-check=ok` t=45 s, both launches `art=` the state row's md5, `tv_health` 12/12 | — | re-verify on the next v48 build |
| 3 | **`mask.sh` counts a failed stop but not a unit that stays `active` after its stop exited 0** — **DONE 2026-11-03** (fixed 2026-11-01; re-verified live on the TV on a freshly mains-cold-booted v47 set, boot rooted t=37 s): `already=29 stopped=29 fail=0 killed=1 reload_ok=1 loop-check=ok activating=0 listed-activating=0 listed-running=0 newhome=active` — the is-active parsing found no listed unit active/activating after the stop pass, and the kill pass removed one leftover `p2p-asm-UI` process | — | offline cases in `test_debloat.py`; the live run is recorded in `CHANGELOG.md` 2026-11-03 and `debloat/AGENTS.md` |
| 4 | **`HEAD` answers with a body; `OPTIONS` is served as `GET`** — **DONE 2026-11-03 (pinned, not fixed; the 2026-10-31 decision stands)**: two checks in `tools/test_server_unit.py` assert both lanes, so an accidental change shows as a visible test diff; server behaviour unchanged | — | `python -I tools/test_server_unit.py` passes including the two new checks |
| 5 | **Beacon tokens are self-service** | none — *by design*; the LAN is the boundary | revisit only if the server is exposed beyond the LAN (`SECURITY.md`) |
| 6 | **High-half read mechanism** — **DONE 2026-11-03**: passive `/proc` + device-tree reads over 31337, then deliberate read-only high-PA reads through the browser stub (video30 —
the stub's node). The "video40 DMA window (~512 MiB)" theory is **refuted** — the cause is a 156 MiB no-map carve-out (DT reserved@0-4) at phys 0x40000000-0x49C00000; `0x46000000` itself reads, pages beyond wedge the stub; the top 104 MiB of the linear map reads fine; the v38 `high-scan` verdicts were re-read against the measured map. Full evidence and verdict corrections in `OPEN-ISSUES.md` item 2; no boot-path change (a high task/cred value still reads foreign content — model corrected 2026-11-05: the band holds real kernel allocations, the video-node view aliases it; attempt 2 stays the floor) | — | record complete in `OPEN-ISSUES.md` item 2 + `CHANGELOG.md` 2026-11-03 |
| 7 | **Portability** — no second model/firmware tested | a second TV | the four gates and the file-by-file checklist in `PORTABILITY.md`; record each unit there |
| 8 | **Debloat tier 2b (Control Center layer)** — **partially done 2026-11-05**: batch 4 (game trio, 69 rows) applied and cold-boot passed 12:31; batch 5 (`ghdaemon`/`ghservice` + Screen Mirroring) and batch 6 (utterance core) applied, **73 rows**, **cold-boot passed 12:59** (masks 29/29, `tv_health` 16/16; boot attempt 2 at t=71). The remaining 17 Home/TV Plus/HbbTV/Health/TAP/coupled ids still need the Control Center layer | owner decision + measurements | next moves are listed in `debloat/AGENTS.md` |
| 9 | ~~**Opportunistic: watch `long-exit` fire for real**~~ — **DONE 2026-11-04**: the branch fired live (`long-exit attempt=5 count=1`, recovery ~25 s vs. the v44 five-minute sit; the coherent long pass also verified on its SUCCESS side). Long mode was entered per the v45 acceptance doc's "force the bad case" — `/tmp/.dsh_try` pre-set to 4 over the root channel, then a detached-kill restart; the degraded pass itself was natural. Of six natural deploy restarts that session, five rooted on attempt 1 and one (roll 6, `fast-exit attempt=1`) on its attempt-2 re-roll. One new hardening note: the degraded pass's `.dsh_try` write silently failed — explained after review as the diagnostic's root-planted counter (a normal boot creates it as uid 5001 and updates it fine); the residual gap (unverified counter writes) is closed in v48 (deployed 2026-11-04; cold boot passed 22:11; `OPEN-ISSUES.md` item 8). Evidence: `CHANGELOG.md` 2026-11-04 + `AGENTS.md` §7; count=2/count=3 remain offline-tested only | — | recorded |
| 10 | **v48 cold-boot acceptance** — **DONE 2026-11-04 22:11**: deployed 22:01 (SIZE=43008, md5 `bf3df7dc…`, `PREV_IL=0df29b15` = v47 backup, `TOKEN_FILE=<BEACON_TOKEN>`, `ART_FILE=bf3df7dc…`, `COPY=ok`, `DEPLOY_DONE`); the mains-cycle boot launched t=28 s (attempt 1 `high-alloc … fast-exit`), attempt 2 `direct-patch uid=0` t=36 s, `ROOTCHAN` t=36, `masks=29 stopped=29 killed=4 fail=0 missing=0 activating=13 listed-activating=0 loop-check=ok newhome=set(0),loop-started` t=42 s; both starts `art=bf3df7dc…`; `tv_health` 16/16; zero `counter-write-failed` lines | — | recorded |

Nothing in the list blocks day-to-day use: the TV roots on every cold boot, the
masks come back on their own, and a deploy is verified with `id -u` = 0.

## First commands for the next agent

```sh
cd <this repo>
git log --oneline -5                  # where the session ended
python tools/test_all.py              # 17 offline layers
python tools/update_state.py --check  # §1 state row vs artifacts/state.json
python tools/sanitize_for_public.py --check

python tools/beacons.py               # per-boot verdicts; --json for machines
python tools/root_shell.py "id -u" <tv-ip>
python tools/tv_health.py --tv <tv-ip>   # 12 checks: debloat registry vs TV
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
- **The physmap node is exclusive: the payload must stay on `/dev/video40` and
  the browser stub uses `/dev/video30`. Never "cycle on busy"** — `EBUSY` is
  retried, `ENOENT`/`ENODEV` advances the node (trap 3).
- **Load the exploit page in a fresh browser session.** The browser preloads its
  first renderer at boot; a page loaded into that process fails the anchor step
  (`elf_base = 0xafaae350 [✗ invalid — abort]`, 2026-11-01) because the heap
  state differs.  Quit the browser fully, reopen it, then load the page: the
  fresh renderer found `0xafa4f000 [✓ ELF]` and paired on the first try.  The
  `/save` dump names the abort reason, so this is diagnosable from the PC.
- `root.ps1 -Force` is the redeploy path; it rotates the beacon token (expected,
  saved automatically) and only reports success on `id -u` = 0.

Deeper: `AGENTS.md` §8 (all 19 traps) and `docs/FAILED.md` (dead ends to
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
