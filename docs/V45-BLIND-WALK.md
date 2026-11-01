# v45 — exit LONG mode on a rootless pass

Status: **implemented, deployed and cold-boot verified 2026-11-01.** Artifact
41,984 B, md5 `35cc7577…`; the TV runs it since 2026-11-01 16:15 (the deploy
relaunch rooted in 10 s, the mains-cycle boot on attempt 2 at t=37 s with
`masks=29 … loop-check=ok` at t=44 s and **no `long-exit` line** — the normal
path is untouched). Written after the v44 deploy restart, which hunted for five
minutes in one process.

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

The critical detail: **the long pass was not blind.** It found and latched its
landmark child; what it could not read was `self` (the payload's own task), and
the parent pointer translated into junk, and the process-wide cred-scan budget
was already spent. So no in-process retry could help — the mapping was stale in
exactly the paths that matter, and the process kept re-reading it. The cold boot
(fresh process, fresh mmap) rooted on attempt 3 in 38 s.

## The rule (as built)

**Any LONG-mode pass that ends without root exits for a fresh process**, because
the process has proven it cannot make progress against its own mapping. The
`seen=0`-only criterion the first draft proposed would *not* have fired on the
2026-11-01 pass (the child was latched) — that is the correction this version
records.

- Long mode = attempt > 4. The pass is the six rounds `{0,0,8000,15000,25000,30000}`.
- After the round loop, if `getuid() != 0`: `CloseDevice(); KillChildren();
  Beacon("long-exit attempt=<n> count=<k>"); Environment.Exit(0)`.
- Bounded per boot by `/tmp/.dsh_long` (`LongExitMax = 3`, tmpfs, so it resets at
  boot like `/tmp/.dsh_try`). After 3 exits the old 120 s in-process idle returns,
  so a pathological boot cannot become a relaunch storm.

### Where

`payload/Program.cs`, `Main()`: the `if (fastMode)` fast-exit block is followed by
the new long-exit block, then the original idle. `TryFile`/`LongFile` sit next to
each other in the constants block.

### Why it is safe

- It is the same argument the v33 `high-alloc` gate already encodes: a read
  failure is **address-dependent**, and only a fresh process re-rolls the address.
  Waiting cannot help; the v31 experiment (10 s last wait) made the cold boot worse
  (132 s vs 51 s).
- A rootless pass has no candidate it managed to patch — `getuid()` was checked
  immediately before the exit, so nothing usable was lost. (If it had patched, the
  loop would have rooted.)
- Cost is bounded: at most 3 extra AUL relaunches in the pathological case, and
  normal boots never reach LONG mode (attempt 1-3).
- A *successful* long pass is untouched: `getuid() == 0` returns before the gate.

### Cost to know about

Each fresh process also resets the **process-wide** cred-scan budget
(`_scanPatched`, 8 patches). Worst-case collateral across a pathological boot is
therefore 4 processes × 8 = 32 uid-5001 cred patches instead of 8. That is the
accepted class (only uid-5001 creds are ever written, `PatchCred` enforces it),
but do not raise `LongExitMax` without measuring it.

### What NOT to do

- **Do not raise the fast attempts from 4 to 6.** It would have covered this case
  but costs up to ~40 s on every pathological boot; the boot-time regressions are
  documented (v31: 132 s) and attempt 2-3 is the accepted floor.
- **Do not retry the content scan.** Its budget is process-wide by design; a
  second pass would just patch more foreign creds.
- **Do not remove the `CloseDevice()`/`KillChildren()` before the exit.** AUL's
  relaunch would race the dying process for video40 and could inherit landmark
  children (traps 3 and 8).
- **Do not make the exit unconditional for fast mode** — fast mode already exits;
  the two gates must stay separate so the fast attempt budget in `/tmp/.dsh_try`
  still works.

## Acceptance on hardware

1. Normal cold boot unchanged: root by attempt 2-3, `tag=exact`, masks line —
   compare against the v44 numbers in `AGENTS.md` §1 (38 s, attempt 3). No
   `long-exit` line on a normal boot.
2. Deploy-restart path: force the bad case if it recurs, or accept the first
   natural occurrence — expect `long-exit attempt=N count=1` and a relaunch
   instead of a five-minute hunt; `tools/beacons.py` decodes it as `LONG-EXIT`.
3. The counter is per boot: a `count=3` line means the next long pass will idle
   (power-cycle from there).
4. Boot-time envelope inside the recorded range; a regression on a normal boot
   means the gate fired on a slow-but-readable pass — check the preceding rounds.
5. Rollback: the v45 deploy saves the v44 DLL as `payload_backup.dll`; restoring
   it (or `uninstall.sh`) is the documented path.

## Related

- `AGENTS.md` §8 trap 18, §9 "v45 hardening to preserve".
- `docs/LOGGUIDE.md` → `LONG-EXIT` and `BLIND-WALK`.
- `tools/wait_rooted.py` — the launcher-side gate that stops a hunting payload
  from being reported as "payload active".
- `root.ps1` prints the exact recovery (power-cycle) when the gate times out.
