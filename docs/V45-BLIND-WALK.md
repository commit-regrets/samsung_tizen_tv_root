# v45 design note — exit LONG mode on a blind walk

Status: **proposal, not implemented.** Written after the 2026-11-01 v44 deploy,
where the post-deploy restart hunted for five minutes without ever seeing a
landmark. Implementation needs a new artifact and a cold-boot session.

## What happened

`deploy.sh` restarts the app inside the same boot (`kill -9`, then AUL relaunches).
On 2026-11-01 the relaunched v44 payload burned all four fast attempts and then
sat in LONG mode:

```
attempt 1: child=… tag=exact, parent=c2d42e00 (high) -> high-alloc fast-exit
attempts 2-4: fail no new PHYRFORK seen=0 … (tail: empty)
attempt 5 (long retry mode): round 3 found child=cb6b5080 tag=exact, but
  self=00000000, parent=e099b980 with junk cred, cred-scan miss patched=6 total=8
  -> fail round 3 … fail round 5, then the 120 s idle loop
```

`seen=0` with an empty `tail:` means the task-list walk read **nothing at all** —
the app's own task pages were stale. No in-process retry can fix that: LONG mode
keeps the process alive and re-reads the same bad mapping, so it re-reads the same
blind state. The cold boot (a fresh process and a fresh mmap) rooted on attempt 3
in 38 s.

## Proposal

When a **whole long-mode pass** produces no positive evidence — i.e. every round
ended in `fail no new PHYRFORK seen=0`, `maybe` was never latched, and `pre` was
empty — treat it as a blind read and exit so AUL relaunches a fresh process.

Bound it with a per-boot counter (`/tmp/.dsh_blind`, the same tmpfs trick as
`/tmp/.dsh_try`): at most **3** blind exits per boot. After that, fall back to
today's idling behaviour, so a persistently blind boot cannot become a relaunch
storm.

Beacon the decision: `blind-exit attempt=<n> count=<k>`.

### Where

`payload/Program.cs`, `Main()`'s round loop: after the round loop ends and before
the `Thread.Sleep(120000)` idle, if `!fastMode` and the pass latched nothing
(`seenFork` 0 in every round, `maybe` never set), read/increment `/tmp/.dsh_blind`
and `CloseDevice(); KillChildren(); Environment.Exit(0);` within the cap.

### Why it is safe

- It is the same argument the v33 `high-alloc` gate already encodes: a read
  failure is **address-dependent**, and only a fresh process re-rolls the
  address. Waiting cannot help; the v31 experiment (10 s last wait) made the cold
  boot worse (132 s vs 51 s).
- A blind pass carries *no* evidence, so nothing is lost by exiting: there is no
  candidate to patch and no scan worth running (`_scanPatched` is process-wide and
  already spent by then).
- The counter bounds the cost at 3 extra AUL relaunches (~15-20 s each) in the
  pathological case; normal boots never reach LONG mode (attempt 1-3).
- Any evidence at all (`seen>0`, a `maybe` latch, a child) keeps the current
  idling behaviour, so a *slow but readable* boot is unaffected.

### What NOT to do

- **Do not raise the fast attempts from 4 to 6.** It would have covered this case
  but costs up to ~40 s on every pathological boot; the boot-time regressions are
  documented (v31: 132 s) and attempt 2-3 is the accepted floor.
- **Do not retry the content scan.** Its budget is process-wide by design; a
  second pass would just patch more foreign creds.
- **Do not exit unconditionally in long mode.** Slow cold boots are what long
  mode exists for; the gate must be "no evidence in a whole pass".

## Acceptance on hardware (when it is built)

1. Normal cold boot unchanged: root by attempt 2-3, `tag=exact`, masks line —
   compare against the v44 numbers in `AGENTS.md` §1 (38 s, attempt 3).
2. Deploy-restart path: force the bad case if it recurs, or accept the first
   natural occurrence — expect `blind-exit` + a relaunch instead of a 5-minute
   hunt, and `tools/beacons.py` showing `BLIND-WALK` on the failed pass.
3. `tools/beacons.py` on the boot must not report `BLIND-WALK` for a boot that
   rooted (the analyzer already derives it only when nothing rooted).
4. Boot-time envelope must stay inside the recorded range; a regression means the
   gate is firing on readable-but-slow boots (check `seen` in the beacon lines).
5. Rollback: the v45 deploy saves the v44 DLL as `payload_backup.dll`; restoring
   it (or `uninstall.sh`) is the documented path.

## Related

- `AGENTS.md` §8 trap 18 (deploy restart can land in the stale window).
- `docs/LOGGUIDE.md` → `BLIND-WALK`.
- `tools/wait_rooted.py` — the launcher-side gate that stops a hunting payload
  from being reported as "payload active".
- `root.ps1` prints the exact recovery (power-cycle) when the gate times out.
