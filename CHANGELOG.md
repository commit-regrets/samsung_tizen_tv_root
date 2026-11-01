# Changelog

All notable changes to this toolkit, newest first. Dates are day-level and times
are deliberately omitted — the *why* of a change belongs here, the *how* belongs
in `docs/`.

**Maintenance rule:** every change to the scripts, payload, server or docs gets an
entry here, under `Unreleased` if it is not part of a dated batch. A change with no
entry is an incomplete change. `AGENTS.md` repeats this rule for agents.

> **Archive:** the 2026-10-20 .. 2026-10-25 entries (the v1..v37 payload
> lineage, the boot-tuning passes, the browser-chain bring-up) moved to
> [`docs/CHANGELOG-ARCHIVE.md`](CHANGELOG-ARCHIVE.md) - verbatim, nothing
> edited. New entries still go here.

---

## 2026-11-01 — `docs/HANDOFF.md`: a cold-start page for the next agent

The state of the project was spread across `AGENTS.md` (state, procedures,
traps), `docs/OPEN-ISSUES.md` (work list) and the changelog (why). A fresh
agent had to read all three before it could even tell what was done. New
`docs/HANDOFF.md` is the one-page answer: where things stand (repo, TV, server,
boot numbers), what landed this session, a **prioritised pending table** where
every row names what it needs (TV / owner / nothing) and how to prove it, the
first commands to run, and the short list of rules that cost hours.

It deliberately carries **no artifact md5/size/token** — those stay
single-sourced in the §1 state row — and it is now in `test_docs.py`'s
`LIVING` list, so a stale claim in it fails the suite like anywhere else. The
`AGENTS.md` read-first paragraph points at it.

## 2026-11-01 — v45: LONG mode exits for a fresh process instead of hunting in one

The v44 deploy restart exposed the last dead end in the retry design: four fast
attempts are allowed, then LONG mode keeps **one process** alive for good. When
that process's mapping is stale, the pass ends without root and the payload idles
for 120 s and repeats the same reads — it found the landmark child but could not
read `self`, the parent pointer translated to junk, and the cred-scan budget was
spent. Five minutes later nothing had changed; the mains cycle rooted on
attempt 3.

**The fix (v45):** a LONG-mode pass that ends without root now exits —
`CloseDevice()`, `KillChildren()`, beacon `long-exit attempt=<n> count=<k>`,
`Environment.Exit(0)` — so AUL relaunches a fresh process, which is the only
thing that re-rolls the mmap. Bounded by `/tmp/.dsh_long` at **3 exits per boot**
(tmpfs, so it resets at boot like `/tmp/.dsh_try`); after that the old idle
behaviour returns, so a pathological boot cannot become a relaunch storm.

The design note's original criterion was **wrong** and is corrected in
[`docs/V45-BLIND-WALK.md`](docs/V45-BLIND-WALK.md): it proposed firing only on a
fully blind pass (`seen=0` in every round), and the observed pass *had* latched
its child, so that gate would not have fired. The rule is therefore "any rootless
long pass". Cost to know: each fresh process also resets the process-wide
cred-scan budget, so worst-case collateral across a pathological boot is 32
uid-5001 cred patches instead of 8 — recorded in the note rather than silently
accepted.

Also: `tools/beacons.py` decodes the new beacon as `LONG-EXIT`, and the
`BLIND-WALK` hint now says v45+ exits by itself (power-cycle only applies to v44
and earlier). `tools/test_constants.py` locks the counter, the cap, the beacon and
the ordering (device/children released before the exit); `tools/test_logs.py` has
a fixture where the long pass exits and the relaunch roots, asserting `LONG-EXIT`
is decoded and no `BLIND-WALK` is claimed.

Artifact: 41,984 B, md5 `35cc7577c102ad04f0bb8522e974f7d9`, reproducible
(two builds identical). **Deployed over 31337 the same day** (`COPY=ok`,
`DEPLOY_DONE`, `PREV_IL` = v44): the deploy relaunch rooted in 10 s and
`root.ps1` verified it with `id -u` = 0 - the first use of the honest gate on a
real deploy. **Cold-boot acceptance PASSED 2026-11-01 16:15** (mains cycle):
attempt 1 `fast-exit` (t=32 s, the allocation lottery), attempt 2
`tag=exact` + `direct-patch uid=0` at t=37 s, `ROOTCHAN` t=38, `masks=29
stopped=29 killed=4 fail=0 missing=0 activating=4 listed-activating=0
loop-check=ok newhome=set(0),loop-started` at t=44 s, **no `long-exit` line** -
the normal path is untouched. Live: uid 0, `CapEff=0x3fffffffff`, 37
`app_disable='true'` rows, 29 masks, boot row 1, easysetup-daemon active with
NRestarts=0. `tools/beacons.py` verdict: ROOTED at t=37 s of TV uptime.

## 2026-11-01 — review follow-up: an honest post-deploy gate, a budget reset, and the blind-walk signature

The v44 deploy exposed a real gap: `root.ps1 -Force` printed "31337 is back;
payload active" while the *new* payload was still hunting, because the check was
a bare TCP probe and `deploy.sh`'s kill is detached - the dying old app's
listener answered it. Three changes, each pinned by a test:

- **`root.ps1` now proves root after a deploy.** It calls the new
  `tools/wait_rooted.py`, which waits (bounded) for the old listener to drop and
  then for the channel to answer `id -u` = 0. Exit 3 is distinct: rooted, but
  the port never dropped - the previous DLL may still be running, so the launcher
  warns instead of claiming success. On timeout it prints the last beacons and
  the recovery (mains power-cycle) instead of a false "payload active".
  *Tested offline* with an injected port/uid/clock: drop-then-root, never-drop,
  a hunting payload (uid 5001) that must not pass, a flapping channel, no
  listener (uid never asked), the parser, and the CLI contract. The layer also
  asserts that `root.ps1` uses the helper and no longer carries the old claim.
- **`deploy.sh` clears `/tmp/.dsh_try` before its restart.** The payload's fast
  attempt budget lives in `/tmp` and resets only on a successful root, so a
  deploy after a boot that already spent it would relaunch straight into long
  mode - which cannot re-roll a stale read. *Tested* two ways: the deploy happy
  path pre-seeds `tmp/.dsh_try` and asserts it is gone afterwards, and a meta
  check locks the `rm` before `RESTART=kill`.
- **`tools/beacons.py` derives `BLIND-WALK`.** A boot whose whole long-mode pass
  ended `seen=0` every round (the task-list walk read nothing) now gets its own
  finding and hint - "an in-process retry cannot fix a blind read; power-cycle" -
  instead of only "not rooted". *Tested* with the 2026-11-01 log shape and a
  negative case where one round saw a landmark.

Also written: **`docs/V45-BLIND-WALK.md`**, the design note for the actual repair
(exit long mode on a blind pass, capped per boot) with the hardware acceptance
list, because that changes the boot path and needs its own cold-boot session.

`python tools/test_all.py`: **16 layers** (the new gate test added). No payload
change - the TV still runs v44, md5 per the state row.

## 2026-11-01 — v44 deployed and cold-boot verified

Deployed v44 over the 31337 channel at 14:16:55 (through the server restarted
earlier the same day, so the token-file fix was already live):
`SIZE=41472`, md5 `7fce4683`, `PREV_IL=85cd0120` (the v43 rollback copy),
`TOKEN_FILE` rotated (rendered by the new server and persisted at render time -
the token-file fix's first live use), `MASKFILE` 29 units / 23 binaries,
`BOOT_ROW_COUNT=1`, `AUL_RELOAD=ok`, `AOT=already-disabled`, `COPY=ok`,
`DEPLOY_DONE`.

**The post-deploy restart did not root** - the documented attempt-1 stale
window, not a v44 regression. Attempt 1 found `child=... tag=exact` but the
parent read was high (`parent=c2d42e00 cred=e48c0100`) and fast-exited;
attempts 2-4 saw `seen=0` with an empty `tail:` (the walk read nothing
coherently); attempt 5 (long mode) found the child with `tag=exact` again, but
`self=00000000`, the direct parent read `e099b980` with junk cred/real, and
`cred-scan miss patched=6 total=8` spent the process-wide scan budget. Long
mode does not exit, so it cannot re-roll; the mains cycle is the designed
recovery.

**Cold-boot acceptance PASSED 2026-11-01 14:23:02** (mains cycle, no PC touched
during the boot): attempt 1 `tag=exact` + high parent -> `high-alloc ... fast-exit`;
attempt 2 `tag=exact`, `self cred == real`, `self-patch uid=5001` (self-patch
did not stick yet) + high parent -> fast-exit; **attempt 3**
`child=d1ce9140 self=cad25080 pu=5001 tag=exact stale=0`, `self cred == real`,
`self-patch uid=0` at t=38 s, `ROOTCHAN` t=38 s, then
`masks=29 stopped=29 killed=5 fail=0 missing=0 activating=3 listed-activating=0
loop-check=ok newhome=set(0),loop-started` at t=45 s. Live after it: `uid=0`,
`CapEff=0x3fffffffff` under the app's label, 29 masks, 37 app rows (unchanged),
md5 `7fce4683` on the TV. Cold boot to root: **38 s on attempt 3** (two
attempts drew high parents).

**v44's rules seen working on hardware:** `tag=exact` on every hunt across the
failed restart and the boot (the per-run tag is the accept), `stale=0` in these
walks (the fast-exit kills its children, so no leftover was presented), and the
ranked `self` path patched when the task was visible (`self=...` + `self cred ==
real`). The high-scan diagnostic is no longer blind (`hits`/`verdict` vary), but
both high-alloc exits still read `verdict=miss`/`cred-elsewhere` with `cov`
inside the sweep - the high-half mechanism stays open as recorded.

**Launcher false positive, recorded:** `root.ps1 -Force` printed "31337 is back;
payload active" while the new payload was still hunting. `deploy.sh`'s kill is
detached, so the dying old app's listener satisfied the port probe. The honest
post-deploy signal is a fresh beacon (or `root_shell.py id`); noted in
`docs/OPEN-ISSUES.md` rather than changed here.

State: `docs/state.json` moves the TV to v44 (md5/date) and the generated row is
refreshed; `docs/OPEN-ISSUES.md` closes the owed deploy and records the launcher
gap.

## 2026-11-01 — second review: the server-restart blind spot, and the regression suite it earned

A second independent read of the same tree (the PC server this time, plus the
tests themselves) found **one P2** and three test gaps; all are fixed and pinned.

**P2 - a PC-server restart blinded `beacons.log` for a deployed payload.**
`BEACON_TOKENS` lived only in memory. Restarting `server.py` (nothing else
changed) made every token the running payload could send unknown, so each beacon
was refused **and never written to `beacons.log`** - it reached the server
console only. That is the same "no beacon = AUL never launched the app" misread
the 0600 `rootchan.host` fix had just closed, one layer down, and it hits exactly
the cold-boot-diagnostics workflow (start the server, watch the TV's next boot).
The set (used tokens + the last two renders) is now persisted to
`logs/beacon-tokens.json` - HTTP-denied under `/logs/**`, git-ignored, and it
holds nothing `deploy.sh` does not already serve to the LAN - and reloaded at
start. A corrupt or hand-edited file is tolerated; malformed rows are skipped.

**The tests that would have caught it, and the other findings:**

- `tools/test_gateway.py` gained the token lifecycle end-to-end: a **used**
  token survives later renders, an unused one older than the last two is
  refused, and - the regression test - the server is **stopped and restarted on
  the same ports and log dir**, and the live token must still be accepted (the
  evicted one still refused). It also covers the abandoned waiting client
  releasing the single client slot (a Ctrl-C'd `auto_root` used to hold it for
  30 minutes and answer every later tool `BUSY`). Each new assertion was
  mutation-checked: deleting the reload fails only the restart check, and
  restoring the old unconditional trim fails the used-token check.
- **New `tools/test_server_unit.py`** (in-process, over a socketpair): a *class
  table* for the request gate - every `DENY_SUFFIX`/`DENY_DIRS` entry against a
  planted file in lower **and** upper case, `/logs/...`, `..`, `..%2F`,
  `%2e%2e`, a docroot sibling - plus the deploy render, the token
  trim/save/reload round-trip, `log()` never raising on an unwritable file,
  `_client_gone`, and the absolute whole-request deadline. It exists because a
  fixture that only names `server.py` misses the next leaked file. The expected
  deny set is a **constant in the test**, not `server.DENY_SUFFIX`: the first
  draft iterated the module's own set, so removing `.pyc` made the test pass by
  not testing it (found by mutation-checking the draft, and now itself pinned
  by a coverage assertion).
- **New `tools/test_hygiene.py`**: every `.py` in the tree compiles (the tools
  no test imports can rot for weeks), every tracked `.json` parses, and every
  TV-side `.sh` is CR/BOM-free, starts with a shebang and parses under `sh -n`.
- `tools/test_shell.py` now rewrites `/proc/self/attr/current` into the fixture
  tree and seeds it with the **browser** label, so the label prelude is
  exercised (`RELABEL=ok` + the file content) instead of being a line nobody
  checked; an untakeable label must warn and continue (advisory, like
  `deploy.sh`), not abort.
- `tools/sim_rpc.py`'s `hunt_self`/`hunt_new_phyrfork` now end the walk on an
  unreadable comm page, mirroring the payload's `catch { break; }` (the twin
  raised out of the generator instead, so a future fixture would have modelled
  "skip ahead"); a holed-comm-page test pins it.

**Small fixes from the same read:** `mask.sh`'s summary key `start-failures=`
is renamed `fail=` - since the second pass it counts failed stops as well as
failed start-refusals, and the old name read as a stop failure that never
happened; `AGENTS.md` §9 now records the deliberate self-side rank-1 floor (a
`NotOurs` pid still lands at rank 1 for `self`, unlike the child side) so a
later agent does not "fix" it away. Docs updated to match: `LOGGUIDE`'s token
row (a restart is no longer a mismatch cause), `SECURITY`'s token paragraph,
`SERVER-HOSTING`'s render bullet and log table, `TESTING`'s layer list (2b and
4d), `OPEN-ISSUES`' current state and the `AGENTS.md` §1 logs table.

**One-time migration, done on the live set (2026-11-01):** the old server process
(started 2026-10-30 13:06) never wrote the file, so a restart under the new code
would have started with an empty set and refused the running payload's beacons.
The live token was therefore seeded into `server/logs/beacon-tokens.json`
(`used: true`) and verified on scratch ports - a fresh start accepts it, a forged
token is still refused. A future first start on a *fresh* `logs/` has the same
gap: seed the token, or redeploy (which renders and persists a new one).
`server.py` now also prints `[beacon] token set loaded: N entries (M used)` at
start, so that a restart is *visibly* verified instead of assumed - the live
restart on 2026-11-01 showed `1 entry (1 used)`, `GET /index.html` 200, and the
unchanged `uid=0(root)` over 31337 afterwards.

`python tools/test_all.py`: **15/15 offline layers** (was 13 - the two new
layers). No payload change: `payload/Program.cs` and `server/payload.dll` are
untouched, so the artifact stays built-not-deployed and the TV still runs v43.

Also caught while checking the live setup: the **live** beacon token had been
pasted into the `docs/state.json` notes (and therefore the generated AGENTS.md
row) and into this changelog. The sanitizer only matches `tok=<8 hex>` and
`"beacon_token": "<8 hex>"`, so prose slipped through `--check`. The two live
copies are redacted here; a token is not an authenticator in this design (a LAN
host can fetch `/deploy.sh`), but a published credential that the gate claims to
redact is still the wrong default. The next deploy rotates it anyway. The
sanitizer pattern is left as-is deliberately: widening it to bare 8-hex after
the word "token" would flag every historical mention, and the publish checklist
already says to rotate before publishing.

## 2026-11-01 — independent verification pass: two doc/generator fixes

An independent payload review of the uncommitted v44/second-pass tree returned
**0 P0 / 0 P1**. It confirmed the v44 tri-state/ranked rules, the sim twin
equivalence (including the deliberate self-side rank-1 floor for a `NotOurs`
pid), the debloat failure paths, and the server hardening. Two cosmetic items
it found are fixed here:

- `tools/update_state.py` rendered `deployed <TV date>` after the **repo**
  payload row even when the repo builds a version the TV does not run - it read
  as if v44 (`7fce4683…`) were on the TV. When the repo md5 differs from the
  TV's, the row now says `built (not deployed)`; the row was regenerated.
- `tools/sim_rpc.py`: the rewritten v43 test 3's comment said the holed pid word
  sat at `0x20E02FE8`; `0x20E02D10 + O_PID(0x2E8)` is `0x20E02FF8`. Comment
  only - the hole covers the whole page and the fixture was already correct.

Left as recorded, not changed: the ranked-self accept does not beacon its rank
(`stag=`), so a rank-1 `self=` is invisible in the log until `self-patch uid=`
says 5001. The patch itself stays gated by `SameCredPair && CredUid==5001` and
the live `getuid()` check. If it is ever wanted, it is a one-line `child=…`
beacon extension - and it will move the artifact md5.

## 2026-10-31 — second review pass: the TV-side shell scripts, the PC server and the Python lane

The v44 review covered the payload's landmark rules. A second sweep read the
rest of the tree against the recorded traps; every finding below was reproduced
(the debloat ones under **BusyBox 1.37 ash**, which is what the TV runs).

**Debloat scripts — four ways a partial run reported success** (all verified by
running the real scripts under busybox ash with stubbed `pkgcmd`/`sqlite3`/
`systemctl`/`dbus-send`):

- `apply.sh`: a failed **undo-log** write was ignored (POSIX sh does not abort on
  a compound redirection failure), so a batch could be disabled with no replay
  record and exit 0. The header and both per-action writes are now `printf`
  simple commands whose status is tested, and a failure aborts **before** the
  disable.
- `apply.sh`: `if : > "$sentinel"` — `:` is a POSIX **special builtin**, so ash
  terminates at a redirection error *before* the `else`; the documented
  `FAILED: sentinel` line and the picture guard never ran on the TV (Git Bash's
  bash takes the `else`, which is why the offline test passed). Contained in a
  subshell, with the source form locked by `test_debloat`.
- `mask.sh`: a failed `systemctl stop` was not counted, so a unit could be
  "masked but running" while the run exited 0. The failure now increments
  `fail` (which the exit test already reads).
- `unmask.sh`: a failed `daemon-reload` was ignored. The masks stay loaded in
  systemd until a good reload, so this now fails the run like `mask.sh` does.

**deploy / uninstall**

- `deploy.sh` sets `umask 077` and wrote `rootchan.host`/`rootchan.allow`
  without a chmod, so a fresh deploy (after an uninstall deleted them) left
  them `0600 root`. The payload is still uid 5001 when it sends its **first**
  beacon and it reads `rootchan.host` on every one — so every pre-root beacon
  (`start`, `device`, `kernel`, `attempt`, `child`) was silently dropped and
  `beacons.log` looked like "AUL never launched the app". Both files are now
  `chmod 644` (the token already was, after the same bug in v41).
- `uninstall.sh` never took the app's SMACK label. The 31337 channel runs under
  it already, but the **documented browser-lane fallback**
  (`run_root.py "curl .../uninstall.sh | sh"`) runs under
  `User::Pkg::org.tizen.browser`, which cannot write `bin/` — so it always
  failed `IL_FAIL`. It now takes and verifies the label first, like `deploy.sh`.

**PC server (`server.py`)**

- `__pycache__/*.pyc` (byte-compiled `server.py`) was served: `DENY_SUFFIX`
  had `.py` but not `.pyc`. Added `.pyc/.pyo/.pyd` and a `__pycache__` path
  deny, with a gateway test that plants a probe `.pyc`.
- **A whole HTTP request now has an absolute deadline** (`HTTP_REQUEST_TIMEOUT`,
  15 s default). The per-recv timeout let one peer send a byte every few seconds
  and hold the single-threaded accept loop (page, `/pair`, `/deploy.sh`,
  beacons, shell slot) for as long as the 1 MB header cap allowed. Tested with a
  trickled request at a 1 s budget.
- `log()` could raise inside the TV reader threads (disk full/permission), which
  left `rpc_tv`/`tv_sock` set with no reader; it is now best-effort and never
  raises.
- A beacon token that had actually admitted a beacon is no longer evicted: the
  trim kept "the last two renders", so two stray `GET /deploy.sh` calls pushed
  the running payload's token out, after which its beacons were refused and the
  TV never rejoined `TV_PEERS`. Only **unused** renders are trimmed now.
- A superseded stub was closed without clearing `tv_sock`, so after a page
  reload the 9999 console's writer sent into a dead socket; `tv_sock` is cleared
  with the close.
- An abandoned client waiting for a stub (Ctrl-C'd `auto_root`) held the only
  client slot for 30 minutes and `RSET` answered `IDLE` without freeing it. The
  waiter now polls its socket (0.5 s) and releases the slot when the client is
  gone.

**Python lane**

- `kernel_root.patch_full` / `physmap.patch_full` now **shape-check a
  task-pointer cred** (`_sane_cred`) before writing. `root()` and
  `root_cred_via_tag()` read the cred pointer straight out of a task page; a
  stale word whose target `+4` happened to read 5001 could zero 8 words of
  arbitrary kernel memory. AGENTS.md already claimed this gate; now the code
  has it.
- `iter_owner_creds(limit=…)` stops after N hits but **drains the in-flight
  `readmany` batch**; `tv_rootwatch`'s early `break` abandoned up to 16 MiB of
  queued pages and then wrote op 5 onto that socket (shell either never started
  or started behind stale page bytes). Its patch budget is now **process-wide**,
  like the payload's `_scanPatched` (loop mode used to add 8 foreign owner creds
  per cycle), and the scan path no longer claims "rooted" from a content count —
  it says `UNVERIFIED` and asks for `id -u`.
- `tv_rootwatch` no longer dies on one transient RPC error (the cycle body is
  guarded; loop mode re-arms), and its docstring no longer advertises a
  `--shell` flag that does not exist.
- `physmap.readmany` now refuses the stub's over-cap count and rejects ranges
  past `0x46000000` (the known driver hang; the SMACK scan's `0x45F00000` top
  still fits); `RPC.__init__` closes the socket on an unexpected hello error; the
  `0x40008000` image-base candidate reports "above TVPHYS_HI" instead of a
  misleading read failure.
- `smack_relabel.find_tasks_by_tag_scan` returned the **physical** address it
  scanned while every other locator returns a kernel VA and the label matcher
  applies `phys()` itself — so the `--scan` fallback read a wrong frame and could
  never match a task. It returns VAs now (regression test in `sim_rpc`).
- `auto_root.run` detects a refused op 7 (`pid <= 0`) instead of waiting the
  full timeout; `beacons.py --last N` numbers boots from the full log instead
  of renumbering the slice from 0.
- `sim_rpc.direct_parent_patch` now mirrors the v43 **pair rule**: a cred is
  written only when `cred == real_cred`, and `real_cred` is never patched by
  itself. The twin still had the pre-v43 independent patch, so the offline
  oracle endorsed a write the payload refuses (two new tests, both
  mutation-checked).

**Docs:** `USAGE.md`/`AGENTS.md` no longer claim `root.ps1` prints the `id`
check (it prints the command); `SECURITY.md` states what the tokens do and do
not prove (they stop forged/mistaken beacons, not a host that can already reach
port 80 — the LAN is the boundary); `TESTING.md` records the Git-Bash-vs-ash
blind spot.

**No payload change:** `payload/Program.cs` is untouched, so the v44 artifact
stays `7fce4683…` / 41,472 B and the TV still runs v43. `server/deploy.sh` was
edited, so the next deploy picks up the chmod and the label prelude.

**Left open, recorded in `docs/OPEN-ISSUES.md`:** the token is self-service by
design (documented, not fixed); `mask.sh`/the payload do not use `--full` when
listing units (a very long unit name could be ellipsized at 80 columns —
unverified on the TV); `mask.sh` counts a failed stop but not a listed unit that
stays `active` while its stop returned 0; `HEAD` answers with a body and
`OPTIONS` is served as `GET`.

## 2026-10-31 — payload v44: the v43 landmark rules were too coarse (two accept holes)

An independent review of v43 found that the accept rule was written to a
contract the code did not actually implement, in two ways that compound:

- **pid=0 took the legacy latch.** `TaskPid` returned `-1` for both "the page
  did not read" and "it read a pid that is not ours", so a freed `PHYRFORK`
  task whose pid/tgid words read **zero** (the stale shape this project has
  observed: cred lines reading `00000000` while comm stayed coherent) walked
  into the `pu == 5001` prefix branch - and a leftover landmark's real_parent
  chain points at the same app's old task, so `pu == 5001` is exactly what it
  shows. The one true read failure and the positive evidence of a stranger were
  the same value.
- **Last match won.** Every accept assigned `ours = task` unconditionally and
  the walk is prev-chain order with no relation to freshness, so a weaker
  accept visited later replaced an exact one (same for `self`), and the patch
  then used that task's cred. The sim's `[stale, fresh]` fixture could not see
  it because its stale task had a readable pid.
- **`stale=` was cumulative.** It was declared outside the poll loop while
  `seen`/`skip-orphan` reset every poll, so the beacon double-counted the same
  leftover and did not mean what the docs said.
- **The high-scan NUL check was blind to v43 tags.** It required NUL at
  `hit+8`, correct only for the retired constant `"PHYSRPT1"`; every real tag
  (`pid >= 16`) has a hex digit at byte 8, so `hits` stayed 0 and the sweep
  could only ever report `miss`. Read-only and diagnostic-only, but it was the
  measurement behind the high-half question.

Fixes, all in `payload/Program.cs` (v44):

- `TaskPid` is tri-state (`PidRead.Unreadable` / `Ours` / `NotOurs`). Only the
  `catch` - a read that threw - keeps the legacy parent-uid fallback; a pid
  that read zero, disagrees with `tgid`, or has the high half set is refused
  and counted.
- The accept is ranked (exact 3 > pid 2 > prefix 1) for the child **and** for
  `self` (exact tag > our own pid/tgid > legacy `PHYSRPT` prefix), and only a
  strictly better rank overwrites.
- `staleTags` resets per poll, like `seen`/`skip-orphan`.
- The `high-scan` NUL check is `hit + commPat.Length`.

**One deliberate trade, recorded:** a fresh child whose comm has not landed and
whose pid words read stale-mismatched no longer gets the legacy catch-all. That
state is indistinguishable from a stale task by any local evidence, and attempt
2 remains the floor. `tag=exact` was the actual accept on both v43 boot
attempts, so the common path is unaffected.

`tools/sim_rpc.py` mirrors all four (`task_pid` tri-state, ranked
`hunt_new_phyrfork`, new `hunt_self`, `PROBE_COMM` built from `PROBE_PID` so the
tag is 12 bytes and the NUL sits at `len(tag)`; `walk_prev` now ends on a failed
link read as the payload does). v43 test 3 was **rewritten**: it used to plant a
zero-pid task and call it "pid unreadable" - it was asserting the pid=0 accept.
It now puts the pid words in an RPC hole, the only true read failure. New tests:
pid=0 refusal, mismatched-pid refusal, exact-vs-pid clobber, exact-vs-prefix
clobber, and three `self` precedence cases. Each was mutation-checked: reverting
the tri-state makes only the pid=0 test fail (old result:
`child=0xc0f02000 how=prefix`), and reverting the rank makes exactly the two
clobber tests fail.

`tools/test_constants.py` locks the tri-state, the refusal, the rank, the
per-poll reset, the tag-length NUL check, the uppercase-hex tag builder and the
sim mirrors. Docs: `docs/OPEN-ISSUES.md` current state now says v43/41,472 B and
records v44 as built-not-deployed; `docs/LOGGUIDE.md` gains `tag=none`, the
per-poll `stale=` meaning and the high-scan NUL note; `AGENTS.md` §9 gains the
v44 invariants; `docs/state.json` moves the repo to v44.

Artifact: **41,472 B, md5 `7fce4683…`** (clean rebuild reproduces it).
**Not deployed** - the TV still runs v43; installing it is a separate decision
and needs a cold-boot check (`tag=` should still read `exact`; a stale left-over
now reads `stale>=1` instead of being latched).

Not changed in this pass: `debloat/tools/apply.sh` - under Git Bash's `sh` the
reported sentinel failure did not reproduce here (`tools/test_debloat.py` was
green at the baseline), so the TV-side script was left alone rather than changed
blind. The same-day **second review pass** (entry above) later reproduced the
abort under BusyBox ash and fixed it there - that entry supersedes this note.

## 2026-10-30 — v43 deployed and boot-verified; the deploy-restart wait

`deploy.sh` installed v43 at 20:07 (41,472 B, md5 `85cd0120`, a fresh beacon
token, PREV_IL = the v42 rollback copy). The app that the deploy kills did
**not** come back quickly: 31337 stayed closed and no beacon appeared for ~15
minutes (it then ran fine at 20:23), so the first conclusion - "the new DLL is
broken" - was wrong. AUL simply relaunched late.

**Trap for the log guide:** after a deploy restart, read the **on-TV marker**
(`/opt/usr/home/owner/share/root_boot.txt`) before believing a silent
`beacons.log`; the marker keeps every beacon regardless of server reachability.
Do not power-cycle on a 1-2 minute silence.

The 21:25:55 cold boot then verified the hardening end to end - `self-patch` at
t=56 s, `masks=29 ... listed-activating=0 loop-check=ok` - and the marker shows
the new accept path in the wild:

```
t=35s child=c798a280 self=00000000 pu=unread tag=exact stale=0
t=55s child=dc069700 self=d7cd0000 pu=5001    tag=exact stale=0
t=56s self cred=c9fc3900 real=c9fc3900  ->  self-patch uid=0
```

Attempt 1 accepted the landmark by **exact per-run tag** while its parent cred
was unreadable - exactly the case the old code could only latch as `maybe` - and
attempt 2 rooted through `self`. TV live: uid 0, 37 rows, 29 masks, md5
`85cd0120`.

## 2026-10-30 — payload v43: per-run landmark tags, pid/tgid accept rule, cred-pair check

The `PHYRFORK`/`PHYSRPT1` comm names were **constants**, so a landmark left over
from an earlier AUL launch was indistinguishable from this run's; the `pre`
snapshot papered over it but could not cover a landmark created between the
snapshot and the fork, or a reused pid. v43 makes the tags per run and adds two
independent accept checks:

- payload self tag `PHYSRPT`+hex(getpid()); landmark tag `PHYRFORK`+hex(child
  pid), written in the child into a pre-pinned buffer with raw byte writes only
  (no CLR allocation after `fork()`), because 16-byte comm fits 8 chars + 8 hex;
- the hunt order is exact tag -> `task->pid == task->tgid == fork()` pid ->
  legacy parent-uid **only when both pid words are unreadable**. A readable pid
  that disagrees is a leftover and is **refused**, counted as `stale=` in the
  beacon, rather than patched;
- `O_PID 0x2E8` / `O_TGID 0x2EC` come from the same DWARF `task_struct` as the
  TV-measured `cred 0x3F8` / `real_cred 0x3F4` / `comm 0x400`, so the check reads
  the fingerprint-verified layout (and `pid == tgid` also rejects a pthread,
  which would inherit the creator's tgid);
- every task-based patch now requires **`cred == real_cred`** (`SameCredPair`).
  The old code patched the two pointers independently, so one stale word was
  enough to write a cred whose `real_cred` was a different object.

Tests: `tools/sim_rpc.py` mirrors the accept order (`task_pid`, `hunt_new_phyrfork`
with `expect_tag`/`expect_pid`/`stats`) and gained three v43 self-tests (exact tag
beats an older landmark; the pid check accepts a child whose tag has not landed
yet; unreadable pid still uses the legacy latch). `tools/test_constants.py` locks
`O_PID`/`O_TGID`, the tag builder, the refusal and the pair check. Beacons show
`tag=exact|pid|prefix` and `stale=` on the `child=` line.

Artifact: 41,472 B, md5 `85cd0120…`. Deployment is a separate step (deploy.sh +
a restart); the state row records which build the TV actually runs.

## 2026-10-30 — first 29-unit / 37-row cold boot: clean

Mains cycle at 19:29:41, the durable test of the standing set:

`
t=49s  direct-patch, ROOTCHAN 31337
t=49s  masks begin n=29
t=54s  masks=29 stopped=29 killed=4 fail=0 missing=0 activating=1
       listed-activating=0 loop-check=ok newhome=set(0),loop-started
`

Live afterwards: uid 0, **37 pp_disable rows**, **29 masks**,
org.tizen.easysetup-daemon row alse with its **unit active and
NRestarts=0** (the 5 s loop the mask used to freeze is gone because the
daemon now runs), samsung-analytics false, smartthings-client +
smartthings-thing + stfind-daemon alive, and the global ctivating count
back to 0 once the vendor's sleep 100 oneshot finished - the ctivating=1 in
the beacon is that oneshot (see the 16:08 entry), not a loop.

This is the state to reason from: 37 rows / 29 units / 23 binaries, with the
SmartThings stack and the phone-path services untouched, and the phone online
(the owner confirmed it again after this boot, ~19:44).

## 2026-10-30 — standing set applied (37 rows / 29 units), phone confirmed online

The final set is live and accepted: `masks=29 stopped=29 killed=4 fail=0
missing=0 activating=0 listed-activating=0 loop-check=ok`, **37 `app_disable`
rows** (tier 1 10 + tier 2a 5 + voice 22), `org.tizen.easysetup-daemon` and
`com.samsung.tizen.samsung-analytics` both `false` with the easysetup unit
active and unmasked, and `smartthings-client` + `smartthings-thing` +
`stfind-daemon` running. The owner confirmed the phone **online** after the
apply, so this is the accepted standing state (the next mains cycle is the
first boot of it).

Docs reconciled in the same pass so nothing stale survives: `OPEN-ISSUES`'s
banner (v41/34-unit/42-row -> v42/29-unit/37-row) and its item-5 history,
`TESTING` (29/23 locks), `debloat/README` (29 units, and the easysetup unit
recorded as removed), `LOGGUIDE` (a current boot prints `n=29`), the root
`AGENTS.md` §7 batch-3 entry (the cause, not "unproven") plus a new standing-set
entry, `debloat/AGENTS`'s round-4 history, the v42 design brief and the two
2026-10-29 run logs (the easysetup row and unit recorded as removed), and the
investigation doc's "cause unproven" wording.

## 2026-10-30 — SmartThings phone-offline: cause is org.tizen.easysetup-daemon

Owner-confirmed bisect, one variable at a time, 0 masks, analytics left
enabled. Voice 22 and tier 1's remaining 10 stayed **online**. Adding the 6
tier 2a ids went **offline**; re-enabling them with no stack restart (thing
pid unchanged) went **online**, so the thing respawn was not the cause.
Disabling `org.tizen.easysetup-daemon` alone then went **offline**. Its
manifest carries the IoT master/resource metadata that `smartthings-thing`
also provides. It is now denylisted, dropped from tier 2a, and its unit is
off the mask list — masking the unit would stop the same daemon. Re-enabled
and launched; the owner confirmed the phone **online** again (~18:51). The other
five tier 2a ids stayed enabled through the online readings and remain
disableable. Full step log: `docs/SMARTTHINGS-OFFLINE-2026-10-30.md`.

## 2026-10-30 — SmartThings phone-offline: 0/0 is ONLINE; bisecting the rows

Owner confirmed the phone shows the TV **online** after the fully-stock
restore (0 live masks, 0 `app_disable` rows, ST stack restarted).  That
closes "it is something other than the debloat" and re-opens the row
bisect.  `samsung-analytics` stays denylisted (SES privilege) but is not
the cause.  Voice 22 re-disabled → still **online** (18:35).  Tier 1's
remaining 10 added on top (rows 32, analytics stays enabled, stack pids
unchanged) → still **online** (18:37, owner).  Adding the 6 tier 2a ids
(rows 38; thing pid changed 28614→1777 during the disable) → **offline**
(18:42, owner).  Re-enabling the 6 with no stack restart (thing pid still
1777) → **online** (18:44, owner), so the respawn is not the cause.  Next
single variable: `org.tizen.easysetup-daemon` (IoT master/resource metadata).
Full step log: `docs/SMARTTHINGS-OFFLINE-2026-10-30.md`.

## 2026-10-30 — SmartThings phone-offline: samsung-analytics was NOT sufficient

Owner confirmed the phone still showed the TV offline after analytics was
re-enabled and the client restarted.  The SES privilege dependency is real
(the client's tizen-manifest requests it) so the denylist stays, but it is
not the cause of this outage.  TV was then restored to the last known-good
shape: **0 app_disable rows, 0 live masks**, ST client+thing restarted,
policy files parked as `.bak` so a reboot does not re-mask.  That is the
~18:00 state that previously read online; the next phone check decides
whether anything other than the debloat rows is still in the way.

## 2026-10-30 — SmartThings phone-offline: samsung-analytics was the cause

The phone listed the TV offline while `smartthings-client` / `smartthings-thing`
/ `stfind-daemon` were all alive and holding cloud sockets.  Of the 39 disabled
app rows (0 masks), **exactly one** is used by the client:
`com.samsung.tizen.samsung-analytics`.  The client's own
`tizen-manifest.xml` requests the appdefined privilege
`http://com.samsung.tizen.samsung-analytics/appdefined/samsung-analytics`,
which that package provides; `pkgcmd -D` on analytics removes the grant
without killing the client, which is why "stack alive" was necessary but not
sufficient.  Confirmed live: flag `true` -> `pkgcmd -A` -> flag `false`
(rows 39 -> 38), analytics launched, client restarted.

Lists locked so it cannot recur:

- `samsung-analytics` dropped from tier 1 / batch 1 and added to the
  `apply.sh` denylist, with the five SmartThings-stack ids
  (`smartthings-client`, `smartthings-thing`, `smartthingsfind-daemon`,
  `mde-framework`, `tvsensor-iot-service`);
- those three stack ids dropped from tier 2a (9 -> 6);
- `pushd` / `register-device` / `p2p-asm` dropped from the mask/kill lists
  (34 -> 30 units, 26 -> 23 binaries) — they were already ruled out as the
  cause (~1.5 MB) but sit on the phone-control path the owner uses.

Standing disable set at that point was **38 app rows** (tier 1 10 + tier 2a
6 + voice 22) and **30 units**.  **Superseded later the same evening:** the
row-by-row bisect found `org.tizen.easysetup-daemon` to be the cause, so the
final standing set is **37 rows** (tier 1 10 + tier 2a 5 + voice 22) and
**29 units** - see the entry above.  `test_debloat.py` locks all four counts
plus "stack ids absent from tier 2a", "easysetup absent from tier 2a and
from the mask list" and "phone-path units commented not active".

## 2026-10-30 — correction: the SmartThings dependency arrow was inverted, cause unproven

`c09340d`'s subject ("smartthings-client -> multiscreen") and the sentence
"smartthings-client declares multiscreen as a package it uses" describe the
graph **backwards**.  Vetro maps `usedBy` -> inventory `referencedBy`, which
answers *who uses this package*: `multiscreen` appearing in
`smartthings-client.referencedBy` means **multiscreen uses the client**, not
that the client needs multiscreen.  The Q80A menu's COUPLED column never
missed an edge - it is a subset of the same list.

What that leaves: the sharing revert was prudence on a plausible path
(Multi-Screen / D2D is how a phone reaches a Samsung TV on the LAN), not a
proof.  And the phone is **still dead** after the revert and a cold boot, with
every sharing app re-enabled and `multiscreen.service` active - so the cause is
somewhere else and is now being found by bisection:

- baseline live: **0 masks** (session-only; the payload re-masks at next boot),
  every previously masked unit started, 42 app rows untouched;
- `pushd` (the cloud->TV push daemon), `register-device` and `p2p-asm` were
  unmasked and started for the test (PSS 203 / 387 / 901 KB) - all three had
  been down since round 4, which predates batch 3;
- next, if the phone is still dead: the 20 tier 1+2a rows, then the 22 voice
  rows, each with one phone test in between.

The lesson is *not* "the menu is incomplete" (it is not); it is "read
`referencedBy` in the right direction, and do not assert a cause from a graph
you have not checked the direction of".

## 2026-10-30 — batch 3's sharing half REVERTED: it broke SmartThings

The owner reported SmartThings phone control no longer worked after batch 3.
Cause, from the inventory: **`com.samsung.tizen.smartthings-client` declares
`com.samsung.tv.multiscreen` as a package it uses** (`referencedBy`) - and
`com.samsung.tv.multiscreen` was one of the 16 sharing ids disabled an hour
earlier. The optional menu's COUPLED column had listed multiscreen's users as
`slive-daemon`/`tvplus`/`channel-list`/... but **not** smartthings-client, so
the menu alone would never have caught this; the inventory would.

Action, immediately and without bisecting:

- the 16 sharing ids are re-enabled (`pkgcmd -A ... --global`), rows 58 -> **42**
  (tier 1+2a 20 + voice 22);
- `com.samsung.tv.multiscreen.service` - the trap-14a companion mask added with
  the disable - is removed from the mask list and the unit unmasked+started;
  with its app enabled, `app_launcher -r` succeeds and the 5 s loop cannot
  happen, so the list is back to **34 units / 26 binaries**;
- `lists/batch3-optional.txt` now holds **22 voice ids** and a long REVERTED
  block naming all 16 sharing ids, the dependency that caused it, and the
  bisect protocol for anyone who wants the AirPlay receiver's ~7.3 MB back
  (one id at a time, phone test between each, inventory `referencedBy` checked
  per id);
- the list's "not installed" skip reason is corrected: `org.tizen.5-way-function`
  is the mainApp of `com.samsung.tv.PanelKeyApp`, and `...airplay-app-2-dummy`
  is the mainApp of `com.samsung.tv.airplay-app-2` - neither is a package id.

`test_debloat.py` now locks the batch-3 list to exactly those 22 ids and to
"the reverted ids are not active lines", so this cannot silently come back.

**Lesson for the next list change:** the Q80A menu's COUPLED column is
incomplete; the inventory's `referencedBy` is the authority for "who uses this
package", and a keep-side user means a phone/cloud feature may depend on it.
Also: the multiscreen mask entry went in without a q3deps run - it was removed
again, so the 34-entry list has no un-gated name, but the gate must come before
the add.

State after the revert: 42 apps disabled, 34 units masked. The 16:08 cold boot
had run the temporary 35/58 state cleanly; the current 34/42 state is the next
boot's test.

## 2026-10-30 — first 35-unit / 58-app cold boot: clean

The mains cycle after the OTA stack and batch 3 (16:08:54). Rooted
direct-patch at t=49 s and the mask step finished at t=52 s:

    masks=35 stopped=35 killed=4 fail=0 missing=0 activating=1
    listed-activating=0 loop-check=ok newhome=set(0),loop-started

All 35 units are `masked-runtime` with none active (24 `inactive` + 11
`failed`), all 58 `app_disable` rows are true, both sentinels are present,
uid 0, and the picture loop restarted itself (`loop-started`, since the
transient unit dies with the boot). The 38 batch-3 apps stayed down -
the `/proc` scan for `/opt/usr/apps/<disabled id>` found none.

**`activating=1` is `security-emdaemon.service`, and it is not a loop:** a
vendor `Type=oneshot` whose `ExecStart` is `/usr/bin/sleep 100` (a boot delay,
`WantedBy=sysinit.target`, `After=secure-clock.service`). It sits in
`activating start` for ~100 s after every boot and then goes inactive; it is not
on our list and our masks do not touch anything it requires. Recorded here so
the next reader does not chase it as a fourth restart loop.

## 2026-10-30 — batch 3: the optional features this household does not use

**Owner's decisions:** no voice; no AirPlay / Multi View / screen mirroring;
**SmartThings is used** (phone control). Everything follows from those three
sentences.

`lists/batch3-optional.txt` (new, 38 ids):
- **voice, 22 ids** - the whole area minus `org.tizen.multi-assistant-service`,
  which tier 2a already disabled (a repeat `--global` exits 25 mid-batch, so it
  is not repeated). Kills Bixby/Alexa/wake-word engines and the remote's mic
  button.
- **sharing, 16 ids** - casting, mirroring, Multi View, USB-cam view, Remote
  PC/Workspace. **`com.samsung.tv.coba.mobilebff` is deliberately kept** (the
  CoBA mobile backend a phone-side control path could ride on), and
  `org.tizen.5-way-function` / `airplay-app-2-dummy` are skipped because they
  are **not installed on this unit**. The *real* `com.samsung.tv.airplay-app-2`
  is in the list - the vendor menu only carries the `-dummy` placeholder, and
  the receiver was the only resident one (~7.3 MB PSS, 2 procs).
- **the `samsung` area is untouched** - SmartThings, Samsung account, Cloud,
  Pass, SSO all stay.

Applied through the tested script, not by hand: pushed `apply.sh` + the list
over the channel in base64 chunks (the channel is line-based), dry run
`would disable 38 of 38`, then the real run `disabled=38 failed=0`, rows
**20 -> 58**, undo `cat /opt/usr/data/debloat-undo-20261030-155433.sh | sh`.
`pkgcmd -D` does not kill running instances, so the kill pass ran separately:
one process (the AirPlay receiver) was alive and is gone.

**The unit scan found a third restart loop** - trap 14a, exactly as documented:
`com.samsung.tv.multiscreen.service` has `Restart=always`, `RestartSec=5`, and
its `ExecStart` runs `app_launcher -r`; with the app disabled it looped
(7 -> 39 restarts while we watched). It joined the durable mask list
(34 -> **35**) and v42 re-ran: `masks=35 stopped=35 killed=0 fail=0 missing=0
activating=0 listed-activating=0 loop-check=ok newhome=set(1),loop-active`.

To verify by hand: SmartThings phone control should still work (that is what
was kept); anything sharing/voice-related is expected to be gone.

## 2026-10-30 — the five tcc service candidates: measured, and rejected

The next debloat step was meant to be the five extra service candidates from
tcc (~46 MB sum-RSS in the note: `slive-provider-daemon` 17.6,
`mcf-agent-service` 9.0, `screen_sharing` 8.9, `user-presence` 7.4,
`wifi_state_manager` 3.4). Measured live with `/proc/<pid>/smaps_rollup`
instead of trusting the sum:

| candidate | RSS | **PSS** | unit | note |
|---|---|---|---|---|
| `slive-provider-daemon` | 15.7 MB | **1.77 MB** | `slive-provider-daemon.service` | `Restart=always`, /opt app |
| `screen_sharing` | 9.2 MB | **1.01 MB** | `screen_sharing.service` | casting/mirroring |
| `user-presence` | 7.1 MB | **0.49 MB** | `user-presence.service` | presence |
| `wifi_state_manager` | 3.5 MB | **0.08 MB** | `wsm-service.service` | Wi-Fi state |
| `mcf-agent-service` | not running | — | `mcf-agent-service.service` | it is an **app** (`app_launcher -s com.samsung.tizen.mcf-agent`), inactive |

**Total ~3.4 MB of PSS**, not 46 MB — the sum-RSS figure was ~10x the real cost
because these daemons share nearly everything (same inflation that made the
"192 MB services prize" an upper bound). Against that: two are `Restart=always`
services wanted by `starter.target`/bootseq targets, one is the Wi-Fi state
machine the root channel's network path depends on, and one is an app that the
right lever (`pkgcmd -D --global`) would handle as an app row, not a unit.

**Verdict: no-go on all five.** Recorded in `debloat/AGENTS.md` and
`docs/OPEN-ISSUES.md` with the PSS numbers so the next session does not
re-propose them from the old sum-RSS note. The remaining debloat value is
app-level (batch 3) and the Control Center layer, not these daemons.

## 2026-10-30 — review of the 34-unit step: four stale spots, one open question closed

The second review of the OTA-stack change confirmed the counts (34/26, all ten
names, both new binaries) and the trap-9 rejection, and found four more places
still describing the old world:

- **`docs/TESTING.md`** still advertised a "24-unit mask-list lock and
  24-binary kill-list lock"; the layer locks 34/26 and now also asserts the OTA
  names by name - services, timers and paths alike.
- **The v42 brief** still said `SWUCoreTV`/`SWUService`/`SWUVerifierTV` have no
  units - the claim this round corrected. Both occurrences now carry the
  correction and point at `swu-core-tv.service`, `swu-service.service`,
  `swu-verifier-tv.service`, so a later agent cannot re-derive "launchpad
  leftovers".
- **`docs/OPEN-ISSUES.md` item 6** still recommended planting
  `/mnt/backup/OS_UPGRADE_FLAG`. Struck: it resolves to `/mnt/systemrw`
  (trap 9). The mask half of that item is marked done (34 units), and the item
  now records that `fw-usb-update-service.{service,path}` **does not exist on
  this unit** (checked: no unit file, `is-enabled` errors) - so it belongs in a
  "not here" note, not on the list.
- **P3s:** the test lock now names all ten additions including the four
  triggers (`.timer`/`.path`), the debloat AGENTS 24/24 paragraph is labelled
  as the first acceptance rather than "the standing state", and the LOGGUIDE
  example is labelled as the 14:05 24-unit run (a current boot prints 34).

No behaviour change; docs and locks only. `test_all` 14/14, sanitize clean.

## 2026-10-30 — the OTA stack joins the durable mask list (24 -> 34 units)

After v42 made the list durable, adding a unit is a one-line change, so the
whole software-update path went in - and it found a **second restart loop**:

| Unit | Was | Why it matters |
|---|---|---|
| `vdsystem-update-manager.service` | `activating (auto-restart)`, `Restart=always`, `ExecMainStatus=0` | the same bug class as easysetup, live since 14:15 |
| `was-background-update.service` | `active running` (`WantedBy=starter.target`, path-triggered) | background updater alive every boot |
| `swu-verifier-tv.service` | `active running` (`WantedBy=multi-user.target` + two bootseq targets) | the SWU verifier |
| `vdca-update.service`, `swu-auto-upgrade.timer` | `failed` | update path retrying into nothing |
| `swu-core-tv.service`, `swu-service.service` | `disabled/inactive` | **correction:** SWUCoreTV/SWUService/SWUVerifierTV are NOT unit-less - they had units all along |
| the timers/paths (`vdsystem-update-manager.timer`, `was-background-update.path`, `swu-verifier-tv.timer`) | active/inactive | the triggers, so they stop firing instead of failing |

**Gate (q3deps predicate run inline over every unit file):** the only hard
reverse edges are `swu-core-tv`/`swu-service` `Requisite=swu-verifier-tv` and
`swu-factory-usb-upgrade.target` `Requires=swu-verifier-tv` - all three
disabled and off the boot path, and masking the verifier only makes the SWU
core/service/factory-USB paths un-startable, which is the intent. No
`PartOf`/`Conflicts`/`BindsTo` on any added unit; nothing `Wants` them.

**Rejected lever:** the vendor's own OTA switch is
`ConditionPathExists=!/mnt/backup/OS_UPGRADE_FLAG` on the SWU cores. It looks
free, but `/mnt/backup` is a symlink to `/mnt/systemrw` - the trap-9 zone - so
the flag was NOT planted; the units are masked instead.

Lists are now **34 units / 26 binaries** (`+2` kill-list names:
`was_background_update`, `vdsystem-update-manager`; the three SWU binaries were
already there). Tests lock the new counts and the new names.

Applied live without a reboot (an app restart re-runs v42): the lists were
installed on `/opt/usr/data` from the server-rendered committed copies, the
payload process was killed, and 2 s later:

    masks=34 stopped=34 killed=1 fail=0 missing=0 activating=0
    listed-activating=0 loop-check=ok newhome=set(0),loop-active

All ten new units are `masked-runtime` and none is active; zero processes under
the two new binaries; `vdsystem-update-manager` is `failed` with its restart
refused. **The global `activating` count fell 2 -> 0** because that loop was
the remaining one. The boot-time re-application mechanism is already
cold-boot proven; a future power cycle will simply read 34 instead of 24.

## 2026-10-30 — review fixes: the current state is 24/24, and the mask beacons decode

Three findings from the post-acceptance review, all docs/tooling — the boot
itself was fine.

- **The "current state" leads still described the session-only era.**
  `debloat/AGENTS.md` opened with "a 24-unit mask LIST, not 24 masks that are up
  now", and `docs/OPEN-ISSUES.md` with "only that one mask is up right now" —
  true at 12:35, false from 14:05. Both now lead with **24/24 masked, durable
  via v42** (acceptance numbers inline) and keep the 12:35 reading as an
  explicitly labelled History paragraph, so the next reader cannot mistake it
  for the present.
- **The beacon dictionary had no entries for the v42 lines**, although
  `docs/LOGGUIDE.md` claims every beacon is decoded: `beacons.py` would show a
  `fail=` or `loop-check=failed` line as unclassified noise. Added `MASK-BEGIN`,
  `MASK-OK`, `MASK-FAIL`, `MASK-SKIP`, `MASK-UNVERIFIED`, `MASK-CRASH` and
  `MASK-DEADLINE` (the retired v42.0 stop loop, so old logs still explain
  themselves), a "Service masks (v42)" section in the guide with the healthy
  cold-boot shape, and fixtures in `test_logs.py` (healthy -> OK; the 13:07 boot
  -> FAIL + DEADLINE; a missing list -> SKIP; a failed dump + thrown thread ->
  UNVERIFIED + CRASH). Writing the tests caught a defect in the new dictionary:
  `^masks=\d+` matched the clean line too, so every healthy boot reported both
  MASK-OK and MASK-FAIL. `MASK-FAIL` now fires only on
  `fail=[1-9]`/`missing=[1-9]`/`loop-check=failed`.
- **Two smaller truths:** the §1 Boot-to-root row now quotes v42's own number
  (48 s, attempt 1 `direct-patch`, mask step done at t=51 s) instead of leaving
  v41 as the newest datapoint; and the stale local `payload/out/` copy (v41,
  gitignored) was refreshed from `server/payload.dll` — the tracked artifact
  was always right, but a hand-copy would have picked up the old DLL.

`test_all` 14/14, sanitize clean.

## 2026-10-30 — v42 deployed; the first run found (and fixed) the stop pass

Deployed over the 31337 channel with `deploy.sh`: `PREV_IL=1ab4343e..` (the v41
rollback copy), `ALLOW`/`HOST_FILE`/`TOKEN` written, `MASKFILE=debloat-masks.txt
24 entries` + `MASKFILE=debloat-kill.txt 24 entries`, `BOOT_ROW_COUNT=1`,
`COPY=ok`, `DEPLOY_DONE`. The restart rooted in ~1 s.

**The first mask step was wrong, and the beacon said so.** It stopped the units
one `systemctl stop` at a time and gave up at a 45 s deadline:

    masks=24 stopped=2 killed=16 fail=22 missing=0 activating=1
    listed-activating=0 loop-check=ok newhome=set(0),loop-active
    (masks deadline after 4/24 stops)

`masks=24` was right (all symlinks up) and `listed-activating=0` was right, but
22 units were counted "failed" because the loop ran out of time: each
`systemctl stop` serialises behind the previous unit's ExecStop, ~11 s on this
set, so four calls ate the budget while 16 binaries were still alive. The kill
pass then took those 16 down; `pushd.socket` and `fw-update-service.path` have
no process to kill and were left *active* (masked and running) until a manual
stop — measured 0 s for both.

Fix (v42.1, redeployed the same day): **one** `systemctl --no-block stop
<all 24>` (measured 0 s to queue) followed by a bounded `list-units` poll (ten
dumps, 2 s apart) that also produces the counters. `stopped` is now the number
of listed units that the dump confirms are not active/activating; a listed unit
still up after the window is a real `fail`; an unreadable dump is
`loop-check=failed` plus a `masks counters unverified` line instead of a clean
zero. The per-unit stopwatch/deadline is gone.

Redeployed result, in 2 s:

    masks=24 stopped=24 killed=0 fail=0 missing=0 activating=1
    listed-activating=0 loop-check=ok newhome=set(0),loop-active

and a `/proc` scan afterwards found **zero** processes under the 24 listed
binaries; `newhome-fix` is active, all 20 `app_disable` rows still true, both
sentinels present, uid 0. The lesson is in `AGENTS.md` §9 and the brief: the
stop pass must be one batched non-blocking call confirmed from the dump, never a
loop of blocking calls.

**Cold-boot acceptance (2026-10-30 14:05:40, mains cycle, no PC involved):**
rooted direct-patch at t=48 s, `ROOTCHAN` t=48, and three seconds later

    masks=24 stopped=24 killed=3 fail=0 missing=0 activating=2
    listed-activating=0 loop-check=ok newhome=set(0),loop-started

- the masks came back from `/opt` on their own, all 24 confirmed stopped, the
three stragglers killed, nothing missing, no listed unit looping, and the
picture loop started fresh (`loop-started`, because the transient unit dies at
reboot). Live after that boot: 24/24 listed units `masked-runtime` and none
active (18 `inactive` + 6 `failed`), zero processes under the 24 listed binaries,
all 20 `app_disable` rows true, both sentinels present, uid 0, the same v42
artifact. **v42 is done.**

## 2026-10-30 — v42: the payload re-asserts the service masks at every boot

The last piece of the debloat design. The 24-unit mask list only ever lived in
`/run` (tmpfs), so every mains cycle silently restored 23 services — the biggest
remaining debloat win (~192 MB sum-RSS at idle) was session-only, and the one
manual re-run per reboot is exactly the kind of step that decays.

`payload/Program.cs` gains `MaskServices()`, run on its own background thread
after SUCCESS-R00T + `CloseDevice()` (never in front of `RootChannel()`, so a
slow `systemctl` cannot delay the listener): read the root-owned
`/opt/usr/data/debloat-masks.txt` → symlink `/dev/null` into
`/run/systemd/system` → **one** `daemon-reload` → `systemctl stop` each (45 s
budget) → kill stragglers from the optional `/opt/usr/data/debloat-kill.txt` by
`/proc/<pid>/exe` → `SetNewHome` + verify, then start the persistent
`newhome-fix` 30 s loop → restart-loop check → one beacon:
`masks= stopped= killed= fail= missing= activating= listed-activating=
loop-check= newhome=`.

Deliberate properties (each one is load-bearing, see `AGENTS.md` §9):

- **Policy on `/opt`, root-owned — never `share/`.** `share/` is writable by the
  browser app (uid 5001) and this step executes what it reads; a missing list
  skips the step, which is also the documented revert.
- **A name with no unit file is skipped and counted (`missing=`), not fatal** —
  the opposite of `mask.sh`, which aborts because a human is watching. An
  unattended boot step must survive a vendor rename in an OTA.
- **`loop-check=failed` when `list-units` itself fails** — an unmeasured check
  never beacons a clean number.
- **Picture guard is the persistent loop**, not a one-shot: the avocd flag can
  be re-set mid-session (tcc).

Shipped alongside: `server.py` serves `/debloat-masks.txt` and
`/debloat-kill.txt` from the committed `debloat/lists/` files (no generated
copy to go stale), `deploy.sh` installs both under `/opt/usr/data` 0644
root-owned (a failed fetch is a warning, not a deploy failure), and
`uninstall.sh` deletes them.

Offline coverage: `test_shell` (deploy installs both, `MASKFILE=` lines,
uninstall removes them), `test_gateway` (both routes serve the committed lists
byte-identically), `test_constants` (payload, deploy and uninstall name the same
two paths; the list must not be under `share/`), `test_all` 14/14. The
payload-level shell constructs were also exercised on the live TV before the
build: `__OK`/`__FAIL` wrapper, `list-units … ; echo __RC=$?` (920 lines,
`__RC=0`), the loop-start chain (`__ACTIVE`) and `SetNewHome` + verify
(`__OK`, `st=0` on Home — expected).

Build: `34710b0e69ccd54d54715c16bf43f183`, 39,936 B. **Not deployed yet**;
the mains-cycle acceptance is the remaining step.

## 2026-10-30 — review residuals: one live-state truth, one beacon shape, TESTING 4c

Three P3 consistency residuals from the second review:

- **One live-state sentence everywhere.** `debloat/AGENTS.md`,
  `docs/OPEN-ISSUES.md` and `debloat/README.md` now all say the same thing,
  checked live at 12:35: the mask list is 24, **exactly one mask is up**
  (`org.tizen.easysetup-daemon.service`, the targeted test) with `newhome-fix`
  running, and the 2026-10-30 mains cycle cleared the other 23. (AGENTS.md said
  "nothing is masked except the targeted test", the other two said "no masks
  are up" — both were half-true.)
- **Beacon shape has one definition.** `fail=<m>` is now in all three places
  that define it (v42 brief step 6, the brief's acceptance line, parent
  `AGENTS.md` §11): `masks= stopped= fail= missing= activating=
  listed-activating= loop-check= newhome=`.
- **`docs/TESTING.md` 4c matches the layer**: five TV-side scripts (the four
  plus `q3deps.sh`), the q3deps list contract (comment-only list → `FAIL:` +
  exit 2), the documented `cat script | sh -s <list>` form, the piped-list
  refusal, and the fail-closed loop check (`loop-check=failed` on an
  unreadable `list-units`, not "no loops").

## 2026-10-30 — bt-monitor forensic answer: it restores the saved BT state at boot

Owner question: what does `bluetooth-monitor.service` do, and should we block
it too? Read-only forensics (run-log round 7) answered it: the **stack** is a
separate unit (`bluetooth-frwk-service.service` → `/usr/bin/bt-service`,
`sysinit.target`, untouched), and the **helper** (`bt-monitor`) reads the saved
state from `vconf db/bluetooth/status` (currently **1 = on**) plus the
adapter's `Powered` property (196 `Powered` strings, 25 `vconf` refs, two dbus
sockets) and re-applies it after boot — its unit comment says exactly that.
Decision recorded, not changed: it stays excluded from the mask list and the
kill list (a runtime kill only respawns it in 2 s; the boot-time restore is the
piece that matters, and it is the owner's remote). Any future test must be a
mains-cycle test after v42. Also recorded: `dbus-send ListNames` hangs on this
set (two 30 s timeouts) — use `/proc/<pid>/fd`, `grep -a` and `vconftool`
instead.

## 2026-10-30 — second external review: q3deps contract, fail-closed loop check, truth pass

The reviewer accepted the three commits and returned two P2 "do not copy this
into v42" items plus doc drift. All fixed before v42 starts:

- **`q3deps.sh` got the list contract too** (it was the fifth script and was
  missed). It used to answer `q3: 0 coupled of 0 checked (0 = mask list is
  dependency-safe)` and exit 0 for a no-arg or empty/comment-only list — the
  same silent-success class closed in `apply/restore/mask/unmask`, on the gate
  that cleared v42. Now: exit 2 with a usage line, and exit 2 with
  `FAIL: … no valid unit names` when it checked zero units. Tests cover the
  no-arg case (in the shared loop) and the comment-only list.
- **The loop check fails closed.** If `systemctl list-units` itself fails,
  `mask.sh` used to leave `loops/ourloops=0`, print a clean summary and could
  exit 0. Now that is `loop-check=failed`, a `loop-check: FAILED` line, a
  `loop-check=failed` summary field and a non-zero exit; v42 will beacon the
  failed state instead of `listed-activating=0`. The check's counter and its
  `LOOP:` lines now come from the same sanitized reader (an `awk` pass over the
  raw list could disagree on CR/comment lines).
- **Picture-guard readback aligned** between `apply.sh` and `mask.sh`: 0 is not
  a failure while Samsung Home is in front, so only an empty answer warns.
- **v42 spec hardened** before coding: the missing-unit policy is written down
  (payload **skips** and beacons `missing=<n>`; `mask.sh` stays strict — a
  human is there and a typo must be loud; an OTA rename must not fail the boot
  step), the beacon fields are pinned to
  `masks=… stopped=… fail=… missing=… activating=… listed-activating=…
  loop-check=ok|failed newhome=…` (the ambiguous `loops=` is gone), and the Q3
  table explicitly says it covers the 23-entry run only — the 24th unit was
  checked with the same predicate inline on the TV, not by `q3deps.sh` over 24.
- **Truth pass on "how many are masked":** `debloat/AGENTS.md`,
  `debloat/README.md` and `docs/OPEN-ISSUES.md` now say the list is 24, only 23
  were masked live (round 4), the 24th was a targeted remask, and **nothing is
  masked right now** — the 2026-10-30 mains cycle cleared `/run`, which is the
  whole point of v42. `docs/TESTING.md` says 24-unit lock; the stale "3 of 25"
  kill-list comment is 24; `unmask.sh`'s header documents that the picture loop
  (`newhome-fix`) is deliberately left running.
- **Bluetooth claim softened** everywhere (AGENTS rule 4 + state, README, both
  list headers, the v42 brief, OPEN-ISSUES, parent `AGENTS.md` §11): it is
  excluded **on the owner's instruction**, not because it is proven to break
  the remote — tcc blocks `bt-monitor` and reports the remote still works, but
  that is unverified here and ~5.8 MB is not worth the experiment.

## 2026-10-30 — two tcc lessons folded in: persistent picture loop, loop detector

Cross-read of both reference trees before writing v42. Nothing in
tizen-tv-control-center or Vetro blocked v42 (tcc's `systemctl mask --runtime`
is the mechanism we already proved; their `parseinfo.sh` boot hook is the one
our unit falsified; Vetro is app-level only, and its two extra verified ids
`com.samsung.tv.acr` / `vision-data-recognition-service` do not exist on
QNX1D). Two tcc findings did change the code, so they landed first:

- **The picture guard is now persistent, not one-shot.** tcc documents that
  `avocd`'s `new_home` flag can be re-set by Samsung code at any time, so a
  single `SetNewHome` at boot/session start is not enough. `mask.sh` keeps
  the immediate set + `CheckAutoMotionPlus` verify and then starts tcc's
  proven 30 s loop as a transient unit:
  `systemd-run --unit=newhome-fix /usr/bin/awk '…SetNewHome int32:0…sleep 30…'`.
  Idempotent (a second run reports `newhome=active`), `NEWHOME_LOOP=0` keeps
  the one-shot only, `systemctl stop newhome-fix` removes it (transient,
  dies at reboot anyway). The v42 spec now says the same. Verified live the
  same day (`systemd-run` unit active; a throwaway transient unit's
  `dbus-send` returns rc=0, so SMACK does not block it). **Readback trap
  recorded:** `CheckAutoMotionPlus` reads 0 while Samsung Home is on screen
  (Home keeps motion processing off regardless of the flag), so the 0→1
  check is only meaningful with content showing — v42's acceptance says so.
- **Restart-loop detector (tcc's "trap").** A unit whose app is disabled
  restarts every 2–5 s forever. `mask.sh` now reads
  `systemctl list-units --all --no-legend --plain` once, reports the global
  `activating` count for context and **fails the run if any listed unit is
  activating**. First live run of the check found
  `org.tizen.easysetup-daemon.service` at **`NRestarts=654`** and climbing,
  `activating (auto-restart)`, from our own tier-2a app disable
  (`app_launcher -s org.tizen.easysetup-daemon` fails under
  `Restart=on-failure`). No reverse deps (checked live), so it is now the
  **24th unit** in `lists/services-units.txt` — the completion of an app
  disable, not a new decision. Audit of every other `app_launcher` unit of a
  disabled app: `NRestarts=0`. Live-verified by masking just that unit:
  `masked-runtime`, `NRestarts` frozen (759 → 759 over 25 s), state `failed`
  (it had hit its start limit); v42's acceptance therefore counts
  `inactive` **or** `failed` as stopped.
- Beacon/summary parity for v42: `mask.sh` now prints
  `activating=… listed-activating=… newhome=…`, and the brief's beacon shape
  is `masks=… stopped=… fail=… missing=… activating=… listed-activating=…
  loop-check=ok|failed newhome=…` (final shape, pinned in the review-residual
  entry above).
- Tests: `systemctl` stub learns `is-active`/`list-units`/unknown-unit
  `start`; new `systemd-run` stub; assertions for the loop start, its
  idempotency, the fail-on-listed-loop, the report-only-global-loop case,
  and the 24-unit lock. Docs: v42 brief (steps, acceptance, counts,
  root-owned policy path `/opt/usr/data/debloat-masks.txt`), `debloat/AGENTS.md`
  (rule 14 records both traps), README, run-log round 6, parent `AGENTS.md` §11.

## 2026-10-30 — cold-boot readback closes the disable store; Bluetooth excluded

The owner power-cycled the set and the readback settled both debloat questions.

- **All 20 disabled app rows are cold-boot verified.** After the mains cycle:
  channel answers with `id -u` = 0, `select count(*) ... where
  app_disable='true'` = **20**, and both vendor sentinels
  (`/opt/usr/share/systemd/system/canalysis-daemon`, `pisa-service`) are still
  present with their 2026-10-29 timestamps. So the 9 tier-2a rows are no longer
  "inferred from the same store" — the whole store is durable as-is and v42
  does not need to re-assert app disables. Docs updated (`debloat/AGENTS.md`,
  `debloat/README.md`, `docs/OPEN-ISSUES.md`, parent `AGENTS.md` §11).
- **`bluetooth-monitor.service` is excluded, not deferred.** Live inspection
  answers "what does it do": `systemctl cat` shows
  `ExecStart=/bin/sh -c '/bin/fms_bt_monitor_launch.sh ... /usr/bin/bt-monitor'`
  and the unit's own comment is *"bt-service check previous BT-connection
  status and re-activate BT when boot"*; it is wanted by `starter.target`
  **and** `swu-standalone.target`, so it starts at every boot even though
  `is-enabled` says disabled; `Restart=on-abnormal`, `RestartSec=2`; and the
  running process (seen after the reboot; it holds `/dev/micom-msg` and
  `/dev/eeprom`) is the power/standby side of the BT state machine. Masking it
  risks the BLE remote not reconnecting after a power cycle, so it is **out of
  the mask list and out of the kill list** — the kill pass was in any case a
  2 s respawn loop (`on-abnormal` restarts on SIGKILL), not a suppression.
- **`lists/services-bind.txt` is 24 active binaries** (was 25): `bt-monitor`
  removed with the reason recorded in the file, `test_debloat.py` now locks
  both "24 active" and "bt-monitor is not an active entry", and the README,
  `debloat/AGENTS.md` rule 4, the v42 brief and the Q3/Q5 notes say
  DO NOT MASK instead of "candidate, verify first".

## 2026-10-30 — review pass: list contract, mask evidence, 23-unit truth, docs

A third independent review of `debloat/` (after the two 2026-10-30 fix
rounds) found three things that would bite on the next live run, and a set of
doc claims the earlier "all stale docs reconciled" commit had missed.

- **The list is a file argument now — every script.** `apply.sh`,
  `restore.sh`, `mask.sh` and `unmask.sh` all read the list with
  `done < "${LIST:--}"`; `-` is a *literal filename*, not stdin. A no-arg run
  therefore printed `0 of 0` and exited **0**, and the documented
  `cat lists/x.txt | sh restore.sh` form silently activated nothing
  (reproduced). All four now require an existing list file (exit 2 with a
  usage line) and exit 2 when the list yields no valid ids. The stdin form is
  not "fixed" but removed on purpose: the usual invocation is
  `cat script | sh -s <list>`, so stdin already carries the script.
- **The dry run is a gate.** `APPLY=0` exits 1 on a refused entry (it used to
  exit 0), so the discipline-1 dry run can actually stop a bad batch.
  `screen-analysis-dbmgr` joined the `apply.sh` denylist: tcc measured
  picture-processing breakage, and it was only excluded by a list comment.
- **`mask.sh` no longer accepts a unit that does not exist.** A listed name
  with no unit file is `MISSING`, gets no `/run` symlink, and fails the run —
  v42 replays this list at every boot, so a typo would otherwise be reported
  "masked" while the service kept running. The start-refusal is now evidence:
  it runs only after a good `daemon-reload` **and** only when the `/run` mask
  is ours, so a failed symlink can never start the service it was meant to
  suppress (15/15 → 23/23 counters reworked: `missing-units=`,
  `kill-refused=`, `absent-binaries=` added, `bad` no longer doubles as the
  kill-pass error count).
- **Kill pass is testable.** `PROCDIR` (default `/proc`) lets the test point
  the pass at a fake tree; the pass also skips and counts binaries this unit
  does not ship (3 of 25 on QNX1D) instead of treating them as killed.
- **`bluetooth-monitor.service` demoted to a commented candidate.** It was
  added to the mask list *after* the only verified run, was never masked
  live, was not in the Q3 reverse-dependency gate, and the brief says never
  disable Bluetooth. The list is **23** again (what was measured), and
  everything that said 22/23/24 now agrees. `bt-monitor` stays on the kill
  list (it already was in round 4), so only "block restart" is withheld.
- **Claims scoped to the evidence.** `README`/`AGENTS` no longer call all 20
  disabled packages "cold-boot verified": the 11 tier-1 rows are, the 9
  tier-2a rows were read back after their run but not after a boot (both texts
  say so, and `docs/OPEN-ISSUES.md` carries the readback as pending).
- **The quick start can reach the TV.** `debloat/README.md` told you to run
  `python -m http.server 8090`; this PC's firewall has inbound Block rules for
  `python.exe` and Allow rules for `pysrv.exe`, so the TV could never fetch
  the script (the parent `AGENTS.md` documents exactly this trap). It now uses
  `pysrv.exe -m http.server` on Windows and notes why.
- **Tests.** `tools/test_debloat.py` grew the coverage the fixes needed: the
  no-arg/piped-list contract on all four scripts, the dry-run gate, sentinel
  planting/stopping/removal and an unplantable sentinel aborting, `MISSING`
  units, unmakeable masks (zero starts), and the kill pass (a real POSIX kill
  of a process whose `/proc/<pid>/exe` is the listed binary; the platform
  guard is printed as SKIP because Git Bash cannot resolve native symlinks).
  The fixture now materialises unit files and rewrites `/prd`, `/usr/bin`,
  `/lib/systemd/system` and `/etc/systemd/system` in one pass (the old
  `rewrite_binaries` flag was never passed and would have mangled `/prd`).
  Merge determinism also asserts the package count and that the summary
  differs only by the two documented overrides (`zip()` used to truncate
  silently). Git Bash is found at its standard install path instead of
  skipping the whole layer, and `test_all.py` prints `SKIP` (not `PASS`) for
  a skipped layer.
- **Docs drift fixed where the docs gate cannot see it** (`test_docs.py`
  covers parent docs only): `lists/services-bind.txt` now says it is the kill
  list, not a bind-mount list; `docs/REFERENCES.md` drops the falsified
  bind-mount recommendation, the wrong inventory filename and the placeholder
  URL; `qnx1d-disable-plan.md` paths/counts/status; `resource-math.md` is
  titled as what it is (pre-run upper bounds) instead of a duplicated
  "measured" title; the v42 brief points the Q5 vendor switches at the
  optional menu (where they are) instead of "services-units.txt era notes".
  `NOTICE.md` lists the vendored Vetro (MIT) files and stops claiming
  "everything else is original"; parent `AGENTS.md` gains the `debloat/` +
  `test_debloat.py` rows and the v42 item in §11; `docs/TESTING.md` documents
  the new layer (4c); `docs/OPEN-ISSUES.md` gets the debloat/v42 item.

## 2026-10-30 — apply/mask holes: sentinels, reload-safe refusal, kill pass

The script-level bug hunt found apply/mask incomplete against the live
run: canalysis/pisa units ignore `app_disable`, a failed daemon-reload
plus start-refusal would start the service, mask.sh never killed
launchpad copies, undo said `sh $file` (UEP), and a failed apply skipped
picture-guard. Fixed:

- **apply.sh** plants the two vendor sentinels (and stops those units)
  when canalysis/pisa are disabled; undo log is under `/opt/usr/data/`
  with `cat file | sh`; sqlite uses `.timeout 5000`; denylist now
  includes `org.tizen.menu`, `home.sidebar`, and `unified-drm-*`;
  picture-guard runs on the sqlite-false abort too.
- **restore.sh** skips whitespace-only lines, stops at the first flag
  failure, removes the matching sentinels, sqlite timeout.
- **mask.sh** does not `systemctl start` unless daemon-reload succeeded;
  symlink failures and a failed reload fail the script; optional bind
  list kills `/usr/bin/<name>` (and `/prd/usr/bin/<name>`) leftovers;
  tests lock reload-before-stop and "reload fail ⇒ zero starts".

## 2026-10-30 — third review: unit count, Vetro license link, apply failure test

The re-review found bluetooth-monitor on the mask list while every count
still said 13/22/23, a broken `THIRD_PARTY_NOTICES.md` link, and an apply
failure test that reused another fixture's list path (exit 2 "list not
found" plus `0 == 0` calls) so it could not catch a real sqlite-false
stop. Fixed:

- **Mask list is 24**: `lists/services-units.txt`, README, AGENTS, and
  the v42 brief/acceptance now agree. Round-4 run log stays 23/23 (what
  was measured); bluetooth-monitor was added after that run and after
  the Q3 reverse-dep gate (noted, not rewritten as if it had been there).
- **Vetro license**: debloat README/AGENTS point at
  `debloat/third_party/vetro/LICENSE` (that file exists; parent
  `NOTICE.md` does not mention Vetro).
- **apply failure test**: writes its own list, asserts exit != 0, a
  single `pkgcmd -D` (discipline #2 stop-at-first), and undo lines in
  the undo log file (undo is script text, not a live `pkgcmd -A`).
- **Count lock**: `test_debloat.py` requires 24 entries including
  `bluetooth-monitor.service`.
- v42 list-gaps no longer call bt-monitor unresolved; the dangling
  "do not implement line below" parenthetical is gone.

## 2026-10-29 (late) — second review fixes: mask ordering, docs one story

The re-review of the previous fix batch found the mask.sh rewrite landed
without its ordering fix (the file edit was staged but never executed) and
several doc corrections lost. All applied and verified:

- **mask.sh ordering fixed and test-enforced**: pass 1 creates ALL /run
  symlinks, ONE daemon-reload, THEN stop + start-refusal per unit. The
  previous single-loop form ran the refusal test while the mask was still
  inert (reload came after the loop), which could start the service from
  the original file. The test stub now models the reload marker, so a
  misordered mask.sh fails the suite.
- **mask.sh idempotency completed**: a second run in the same boot still
  stops every listed unit (already-masked units were previously skipped
  from the stop pass, leaving running units up). Test-enforced.
- **apply.sh test assertion fixed**: asserts `-D --global`, not just `-D`.
- **Move completed**: parent README points at debloat/ in-repo; debloat
  README is in-repo wording; LICENSE/SECURITY/NOTICE links point at parent
  files; leftover _fix3b.py removed.
- **Docs one story**: AGENTS current state no longer contradicts rule 11
  (cold-boot durability confirmed, holdouts resolved); README no longer
  documents the deleted bindapply or lists the resolved holdouts as
  unit-less; services-units.txt header maps bt-monitor (=
  bluetooth-monitor.service, now on the mask list) and records the DLNA
  trade-off; the v42 brief's self-contradiction resolved (Q5 harvest + Q3
  couplings both recorded, cleared for implementation) and the Q5
  vendor-switch names are annotated in the optional menu.

## 2026-10-29 (late) — debloat/ completed in-repo; sibling repo retired

The independent review of the merged debloat folder found the move
incomplete and several scripts not matching their claims. All fixed:

- **Parent pointers**: README now points at `debloat/` in this repository;
  debloat/README no longer describes itself as a separate repo or curls a
  sibling URL (documented flow: any static server, e.g.
  `python -m http.server 8090 -d debloat/`).
- **mask.sh rewritten to match its claims**: mask + `systemctl stop` +
  start-refusal test per unit (a masked unit keeps running until stopped);
  idempotent (already-masked units counted, same-boot re-apply safe);
  dry-run counters fixed.
- **apply.sh**: stops at the first unexpected failure (discipline #2);
  dead owner-uid resolution removed (`--global` needs no uid);
  `vetrotvapp*` denied by prefix.
- **q3deps.sh**: dots in unit names escaped (was over-matching), searches
  `/prd/usr/lib/systemd/system` and `*.path` too.
- **bindapply.sh/bindrestore.sh deleted** — runtime bind-mounts are
  falsified on this firmware (respawner bypass, run log round 1) and
  bindrestore could not see its own overlays (`/proc/mounts` blind).
  `lists/services-bind.txt` stays as the kill-pass binary list; the
  technique lives in the run log + AGENTS rule 13.
- **Working mechanism landed as tooling**: `tools/mask.sh` uses `/run`
  masks + start-refusal tests — 17/17 masked in the live session, 13/13
  held through respawn. Durable suppression = v42.
- **New test layer** `tools/test_debloat.py` (14 offline layers now):
  apply/restore/mask/unmask under a POSIX sh with rewritten paths and
  stubbed pkgcmd/sqlite3/systemctl/mount — dry-run, undo ordering,
  denylist, injection refusal, failure paths, /run mask lifecycle +
  idempotency, list hygiene, merge determinism (exactly the 2 documented
  Vetro-catalog overrides may flip).
- **Docs one story**: AGENTS current state matches rule 11 (cold-boot
  durability confirmed); disable-plan rows corrected to `--global`;
  REFERENCES records that "Failed to get appinfo" is the
  already-disabled signal, not a reason to avoid `--global`; the DLNA
  trade-off lives in the list header; the v42 brief records both gates
  closed (Q5 harvest + Q3 couplings) and is cleared for implementation.
- **Sibling repo retired** (clean tree at e29336e, parity verified by the
  reviewer; content fully merged into debloat/).

## 2026-10-29 — first live debloat run through the toolkit channel

The samsung-tv-debloat project (separate repo, sibling folder) ran its first
real disable batch through this toolkit's root channel: 11 tracking/ad
packages disabled, ~25.9 MB of running ACR/ad processes freed (distinct
processes), undo log on the TV. The run validated the toolkit-as-enabler role and surfaced two
findings recorded there: UEP blocks script files exactly as `FAILED.md`
documents (`cat | sh` workaround), and the toolkit's HTTP server doubles as
the file-push path for TV-side scripts (temporary files under `server/`,
removed after the run). Tooling and run log: `samsung-tv-debloat/models/
qnx1d/run-2026-10-29-tier1.md`.

## 2026-10-27 (publication prep) — sanitize the live credential, drop agent scaffolding

Audit of the tree against a public push (the working tree was clean; the history
is a separate problem, see `docs/PUBLISHING.md`).

- **`sanitize_for_public.py` now detects per-deploy credentials by shape**, not
  only the known-token list: `tok=<8 hex>` and `"beacon_token": "<8 hex>"`.
  Before this, `--check` passed while the live beacon token sat in
  `AGENTS.md`, `docs/OPEN-ISSUES.md` and `docs/state.json` — exactly the class
  the tool exists to catch. `tok=deadbeef` (the documented forged-token
  negative test) is explicitly allowed. `test_sanitize.py` covers both.
- **The live/historical beacon and pairing tokens were placeholdered** out of
  AGENTS (the generated row is regenerated from `state.json`), CHANGELOG,
  OPEN-ISSUES and state.json. The tokens were dead after the last deploy, but a
  public tree has no reason to carry any of them.
- **`.zcode/agents/*` were tracked despite `.gitignore` saying `.zcode/` is
  scaffolding** (six stale agent prompts, one still claiming "v37-on-TV /
  v39.1-in-repo"). Removed from the index; the directory stays local.
- `.gitignore`'s payload comment still described the v39.2 33,280-byte artifact
  and omitted `SIZE_WANT`/`@BEACON_TOKEN@`; corrected.
- **New `docs/PUBLISHING.md`** — the pre-flight gate plus the history-reset
  procedure. The private history (`git log -S '<TV_IP>'`, and commit
  messages with tokens) must not be pushed; publish an orphan commit or a
  filter-repo rewrite.
- Verified: `test_all.py` green (12 layers), `sanitize_for_public.py --check`
  clean, `update_state.py --check` clean.

## 2026-10-27 (late) — docs-consistency gate: stale claims now fail the suite

The two sweeps showed doc drift is enumerable: the same claim classes broke in
three-plus files each.  `tools/test_docs.py` (new `test_all.py` layer
`docs-consistency`, 12 offline layers now) turns them into checks:

- **Banned patterns** (one per past incident): "update WANT=" / "update the
  deploy constants" (rendered gate since v39), "cycles videoNN / three nodes"
  (the v39.1 EBUSY-retry invariant), "binds 0.0.0.0:31337" (route-derived since
  v16), ".NET SDK 6+" (global.json pins 10.0.x), "ARM32 LPAE" (VMSPLIT_3G).
- **Required tokens**: the current mechanisms must stay documented -
  `0xF0400000` (zoneinfo boundary), `tok=`, `rootchan.token`, `POST /pair`,
  `ENOENT/ENODEV`, `EBUSY`, `errors="replace"` - each mapped to the files that
  describe it.
- **Artifact hygiene**: md5s and byte sizes are single-sourced in the AGENTS.md
  generated STATE block (+ state.json, + dated history); living prose must point
  at the state row, not hand-copy numbers.  The offenders found on the first
  run were de-hardcoded: README's payload table row, TESTING's md5/size
  mentions, and three places in AGENTS.md outside the STATE block.  The
  OPEN-ISSUES current-state header is exempt by design (a per-session snapshot,
  refreshed by hand).

Matching is backtick-insensitive; dated-history files (CHANGELOG, archives,
REVIEW-HISTORY) are exempt - they are records, not claims.  When a future
change makes a check wrong, the fix is to update the doc AND the check, with
the incident named.

## 2026-10-27 (late) — docs sweep completion: the six partially-read files done in full

The earlier sweep had read eight docs fully and only grep/section-checked six.
Those six are now read end to end and fixed:

- **EXPLOIT.md had a real internal contradiction:** the address-space section
  measured `high_memory = 0xF0400000` (zoneinfo) two paragraphs above a
  "high-half" section that still claimed "those VAs are not translations of the
  frames that were meant" and "still unmeasured: the exact high_memory value".
  Rewritten to the current model: `0xE0000000` is inside the map, the failures
  are the video40 DMA window, and the remaining falsifiable checks are the
  deliberate high-PA read and the v38 verdict re-read. The stub hello
  description now matches the v40 wire (`PGDB`+token before the device open,
  client-facing 12-byte hello reconstituted).
- **SCRIPT-REVIEW.md:** three stale claims from the v13-era audit - "cycles
  video40/30/60" (now the EBUSY-retry semantics), "binds 0.0.0.0:31337" (v16
  route-derived single address), and "hardcoded hashes / update the deploy
  constants" (rendered per request since v39) - plus a date-context header.
- **ROOT-METHODS.md:** "Binding 0.0.0.0 means..." contradicted the v16 bind two
  lines above; recovery timing updated to ~2 s on v41.
- **PORTABILITY.md:** the read-limit section said the cause was "still unproven
  between pfn limit and cache visibility" - cache was ruled out in v28 and the
  DMA window is the suspect against the measured boundary; "cycles three nodes"
  fixed; deploy render includes TOKEN=.
- **AGENTS.md:** §4 ".NET SDK 6+" now matches the global.json 10.0.x pin, and
  §9's preserve-list header is "v39.x hardening (v41 additions at the end)"
  instead of mislabeling the whole list v41.

`AGENTS.md` (all 750 lines), `EXPLOIT.md`, `FAILED.md`, `ROOT-METHODS.md`,
`PORTABILITY.md` and `SCRIPT-REVIEW.md` have now each had a full linear read;
with the eight files from the previous pass, every doc in the repo has been
read against the v41 state. Suite + sanitizer green.

## 2026-10-27 (night) — full docs sweep: every file checked against v41 state

All 19 docs read one by one; EXPLOIT/FAILED/ROOT-METHODS/BOOT-REGRESSION/
NOTICE/OPEN-ISSUES/REFERENCE-MATERIALS were already current (the hardware-
session agent had corrected EXPLOIT/FAILED to the zoneinfo boundary). Eight
files needed fixes:

- **README.md:** the safety bullet claimed the payload "cycles video30/video60
  if the node is busy" - contradicts the v39.1 invariant (retry video40 on
  EBUSY, advance only on ENOENT/ENODEV). Read-limit paragraph updated to the
  zoneinfo boundary + DMA-window suspect. ".NET SDK 6+" now states the
  global.json 10.0.x pin. Docs table gained TESTING/LOGGUIDE/
  REFERENCE-MATERIALS/REVIEW-HISTORY rows; deploy markers mention TOKEN=.
- **SECURITY.md:** still said the DSHROOT beacon half was open - now records
  v41 closing it and names the deliberate residue (token-less log content,
  legacy unauthenticated PGDB window).
- **TESTING.md:** porting step 3 said "update WANT=/SIZE_WANT= in deploy.sh" -
  that constant no longer exists (rendered per request). Layer list now counts
  11; sim wording for the high half matches the DMA-window explanation.
- **LOGGUIDE.md:** documents the tok= wire prefix, rootchan.token in the proof
  files, the high-alloc row per zoneinfo, and five new server console lines
  ([pair], stub token mismatch, unknown beacon token, sent-no-token).
- **SERVER-HOSTING.md:** hardening list gains the v40/v41 token gates; deploy
  render list gains TOKEN=.
- **USAGE.md:** deploy render description includes the token and rootchan.token.
- **SCRIPT-REVIEW.md / PORTABILITY.md:** dwarf_offsets now points at the ported
  tools/dwarf_offsets.py (was "only in the reference tree"); SDK guidance via
  global.json.

## 2026-10-27 (evening) — codreview.md mined and retired

`docs/codreview.md` (the 2026-10-26 first-review scratch report, git-ignored)
was checked item by item against the repo: every P1/P2 and doc correction in
it had already landed and is recorded in `CHANGELOG.md` /
`docs/REVIEW-HISTORY.md`.  Three pieces existed nowhere durable and were
extracted before deleting the file:

- `browser_payload.js`: a comment warning that `wasm_builder.js` owns hundreds
  of script-scope names (`kExpr*`, ...) - a redeclaration in the payload is a
  parse-time SyntaxError that kills the whole page.  (The `Array.isArray` and
  implicit-global fixes from the same list landed in v39.2.)
- `docs/EXPLOIT.md`: a "shelf life" section - CVE-2024-2887 is fixed in
  Chrome 123, but this firmware's Chromium 120 will never receive it, so the
  renderer primitive stays viable for the firmware's life (and stays a known
  browser hole: keep the set off untrusted networks).
- `docs/OPEN-ISSUES.md` splits bullet: the refactor guidance (wire bytes and
  log tokens identical, `test_gateway.py` the oracle, framework migration
  explicitly out).

## 2026-10-27 (later) — review fixes + self-updating state docs

- **Second reviewer's fixes landed (`7e2a711`):** `dwarf_offsets.py --check`
  walked every DIE of the 123 MB sim vmlinux (>3 min, hanging the suite
  timeout); kernel structs live at CU top level, so it now scans top-level
  children and stops when done (1.3 s), and `test_listwalk.py` treats a DWARF
  timeout as SKIP. Docs were brought to v41 / the zoneinfo boundary
  (`high_memory = 0xF0400000`) everywhere.
- **Self-updating state docs (`tools/update_state.py`).** The Payload row in
  `AGENTS.md` §1 is now a generated block between STATE markers, rendered from
  the artifacts (payload md5/size, blob size - never hand-written) plus
  `docs/state.json` (tracked; the operator-session facts: version labels,
  deploy date, live beacon token, owed items, memory facts). `--check` runs as
  a `test_all.py` layer (11 offline layers now) and fails the suite on drift -
  the same discipline `test_constants.py` applies to code constants; `--fix`
  rewrites the block. After a deploy session: update `docs/state.json`, run
  `--fix`, done.

## 2026-10-27 (verification session) — cold boot, kill -9, uninstall/recover

The three owed hardware gates, run against the live set.

- **v41 cold boot: 36 s.** Attempt 1 `fast-exit` at t=29, attempt 2
  `direct-parent+2f0` at t=36, `SUCCESS`/`ROOTCHAN` t=36; every beacon carried
  `tok=<BEACON_TOKEN>`.
- **`kill -9` recovery: ~2 s.** New pid rooted via `self-patch`, `uid=0`, channel
  serving again.
- **Uninstall verified end-to-end.** `uninstall.sh`: IL back to stock
  `f61f60dd..`, AOT `6c9bdcc4..`, `BOOT_ROW=removed remain=0`, `ALLOW=removed`.
  After a mains cold boot: 31337 stayed closed, no beacons, stock 9197 back.
- **Recover verified, and it exposed two real bugs in `recover.sh`.**
  (1) It grepped `@HOST@/@WANT@` anywhere; the rendered template's guard line
  legitimately contains them, so every rendered script was misread as unrendered
  and then failed the same check. The check is now anchored to the assignment
  lines and knows `@BEACON_TOKEN@` (which a static server cannot render).
  (2) `sh "$SCRIPT_FILE"` is refused by Tizen UEB (`the file is NOT signed!!`);
  the script is now fed through stdin (`cat file | sh`), the same path that
  `curl ... | sh` always used. With both fixed, `recover.sh` with the PC URL
  completed `DEPLOY_DONE`/`RECOVER_DONE` (token `<TOKEN>`).
  `auto_root.py` gained `--script-args` so the browser lane can pass that URL too.
- **Post-recovery cold boot: 49 s.** AUL launched late (first beacon at t=49), so
  attempt 1 direct-patched with no fast-exit; token `<TOKEN>`, v41 md5 unchanged.
  This is the second v41 cold boot (the first was 36 s with attempt 1 fast-exit),
  and it proves the boot row that `recover.sh` re-added actually fires.
- `docs/state.json` (and therefore the generated AGENTS state row) now records
  both cold boots, kill -9 and the closed uninstall/recover cycle.

## 2026-10-27 (unattended session) — v41 live, release pass, porting seeds

Everything below was done with the TV unattended, through the live 31337
channel; the only manual steps still owed are a cold boot on the next visit
and the uninstall/recover cycle.

- **v41 deployed and the beacon token is live.** The payload
  (`1ab4343e…`, 33,792 B) restart-rooted in ~1 s (`self-patch`); every beacon
  now carries `tok=<BEACON_TOKEN>` and the server admits it. Live negative tests
  from the PC: a forged `tok=deadbeef` beacon is refused ("unknown beacon
  token"), a token-less one is logged but never admitted to the shell slot.
  First deploy beached token-less — `rootchan.token` landed 0600 root-owned
  and the uid-5001 payload could not read it; deploy.sh now chmods 644 and the
  fix was applied on the TV before the restart that proved the path.
- **Kernel memory model corrected again (zoneinfo is ground truth).**
  `/proc/zoneinfo`: Normal `start_pfn 0x20000`, HighMem `start_pfn 0x50400`
  → `max_low_pfn = 0x50400`, `high_memory = VA 0xF0400000`. HighTotal
  (303,104 pages) exceeds HighMem present (198,656): Samsung's `si_meminfo`
  is vendor-adjusted, so the earlier meminfo-derived `0xE4E42000` boundary was
  wrong. The observed 0xE0000000 read failures sit INSIDE the linear map —
  the V4L2 node's DMA window (~512 MiB, matching the "past 0x46000000 hangs"
  evidence) is now the prime suspect, not the CPU map.
- **Item 11 closed: the tree passes `sanitize_for_public.py --check`.** The 13
  real tokens (TV/PC IPs, LAN/Wi-Fi/VPN prefixes, firmware and internal
  platform strings) replaced with RFC 5737/TEST-NET placeholders; a rebuild
  proved the Program.cs edit comment-only (md5 unchanged, byte-identical to
  the deployed artifact).
- **Item 4 closed: `tools/dwarf_offsets.py`** (research-tree port). Reads
  kernel struct member offsets from a DWARF vmlinux; `--check` is a
  fingerprint gate (comm 0x400, cred 0x3f8, real_cred 0x3f4) and it PASSES on
  the research sim build — independently reproducing `tasks +0x23c`,
  `real_parent +0x2f0/0x2f4` and the rest of the measured layout. Porting a
  second model is now: get a DWARF vmlinux, run `--check`, trust or re-measure.
- **Item 5 closed: `tools/listwalk.py`** (research-tree port). Back-link
  validated list-head candidates near init_task plus a comm-tag walk with no
  struct-offset assumption — the layout-shift-proof locator for a second
  model. Offline-tested (`tools/test_listwalk.py`, planted sim memory: valid
  ring accepted, broken back-link and unlinked decoys rejected, non-aligned
  task found); registered in `test_all.py` (now 10 offline layers).

- **Verification of this batch found two issues, both fixed here.** (1)
  `dwarf_offsets.py` walked every DIE of the 123 MB sim vmlinux, so `--check`
  hung (>3 min) and `test_listwalk.py` failed by subprocess timeout; it now scans
  CU top-level children and stops once all wanted structs are found (`--check` in
  2 s, fingerprint MATCH), and the gate treats a DWARF timeout as SKIP so it can
  never hang the suite. (2) The state docs still said v39.2 and the meminfo-derived
  memory boundary; AGENTS/README/OPEN-ISSUES/EXPLOIT/FAILED now say v41 and the
  zoneinfo boundary (`high_memory` VA `0xF0400000`).

## 2026-10-26 (deferred-work session) — pairing token, sanitizer, EOL pin

Working the deferred list in `docs/OPEN-ISSUES.md` (token, research ports, EOL
pin). The splits and the payload-side token stay deferred (rationale updated
there); `high_memory` was already measured from the root shell in the hardware
session below.

- **Per-run stub pairing token (v40, PGDB half of the review P1).** The page
  generates a random token per load, announces it to the server (`POST /pair`,
  same-origin checked) and patches it into the stub (`TOK1` placeholder in
  `tools/physrpc.S`, pattern-unique, page aborts on drift). The stub now sends
  `PGDB` + token (8 B) **immediately after connect, before the device open**,
  and `prctl_ret`/`open_ret` (8 B) after it — a slow open no longer looks like
  a silent raw peer to the classifier. The accept loop token-checks and only
  then queues the stub and admits the peer to `TV_PEERS`; the gateway
  reconstitutes the client-facing 12-byte hello, so `physmap.py` and every
  other RPC client is unchanged. A mismatch is refused with a "reload the
  page" log line; with nothing announced (tests, pre-upgrade page) the pairing
  is accepted and logged loudly (a working channel beats a closed one). Blob
  7,696 → 7,720 B, rebuilt and re-embedded, both `--check` modes green.
  **Still open (documented, not fixed):** a forged `DSHROOT` beacon still
  joins `TV_PEERS` and `beacons.log` forgery — both need a payload-side
  token (`rootchan.token` rendered by `deploy.sh`, read by `Beacon()`), i.e. a
  payload change, not a server change.
- **`tools/sanitize_for_public.py` (research-tree port).** Copy mode redacts
  the device/host tokens into a fresh directory (binaries pass through
  byte-exact); `--check` walks the tree (including git-ignored hand-written
  notes) and exits 1 on any private token — it is the pre-publication gate
  OPEN-ISSUES asked for, and currently reports 13 real hits. Seed list from
  this repo (TV/PC IPs, LAN/Wi-Fi/VPN prefixes, firmware/platform/DUID);
  `198.51.100.30.` keeps its trailing dot so the pinned SDK `10.0.301` never
  matches. Covered offline by `tools/test_sanitize.py` (registered in
  `test_all.py`).
- **`.gitattributes` EOL pin.** `*.bin` is now `binary` — the shellcode blob
  was only protected by git's binary *detection* under `* text=auto`, and a
  normalization would have silently broken page == blob == source;
  `*.txt` is pinned LF. Both `--check` modes re-verified after the pin.
- **The gateway test grew the token cases** (announce ok / wrong token
  refused / matching token pairs with the 12-byte hello intact) and the fake
  stubs speak the new 16-byte wire. Server log lines: `[pair] token announced`,
  `[rpc] stub token mismatch …`, `[rpc] no pairing token announced …`.
- **No payload change.** The TV stays on v39.2 (`010946ff…`, 33,280 B); the
  next session needs one fresh page load (new stub) and
  `python tools/test_all.py --tv` to validate the live token path.

## 2026-10-26 (hardware session) — v39.2 deployed and rooted

The TV came back on the network, so v39.2 got its first hardware run.

- **The first deploy was refused with `NEED_RENDER`** even though the script was
  rendered: `deploy_script()` replaced `@HOST@`/`@WANT@` globally, which also
  rewrote the template's own guard (`*@HOST@*|*@WANT@*)`) into
  `*http://<host>*` - a pattern that matches every valid render. Fixed to
  replace only the three assignment lines; `test_gateway` now asserts the guard
  stays literal and the rendered `H` cannot match it.
- **Deploy then succeeded:** `SIZE=33280 MD5=010946ff…`, `BACKUP_IL=exists`,
  `BACKUP_NI=exists`, `PREV_IL=968e1154…` (v37 saved), `BOOT_ROW_COUNT=1`,
  `AUL_RELOAD=ok`, `COPY=ok`, `DEPLOY_DONE`.
- **Restart-root in ~6 s:** attempt 1 `fast-exit` at t=86013, attempt 2
  `self-patch` at t=86021, `SUCCESS-R00T`, `ROOTCHAN 31337`; `id -u` = 0,
  `CapEff=0x3fffffffff`, installed md5 `010946ff…`.
- **New guards verified on hardware:** `sleep 130` returned
  `[timeout: killed after 120s]` (122 s) and the channel kept serving; `dd` into
  `/tmp` died with "File size limit exceeded" at exactly **2 MiB** (`ulimit -f
  2048` is 1024-byte blocks in this busybox).
- **Backups confirmed** in `/opt/usr/home/owner/share` (not the app dir):
  `mcs_orig.dll` (stock IL, f61f60dd…), `mcs_ni_orig.dll` (94,208 B),
  `payload_backup.dll` = v37 (968e1154…).
- **Memory model measured** (`/proc/meminfo`): `MemTotal 1,816,840 kB`,
  `LowTotal 604,424 kB`, `HighTotal 1,212,416 kB` → lowmem ends at phys
  `0x44E42000`, so `high_memory` is ~VA `0xE4E42000`. The old "read limit at
  0xE0000000" was a prediction, not the map end; AGENTS/EXPLOIT/FAILED corrected.
- **Browser-chain log strings are English now.** The vendored upstream payload
  (`hdbreaker` chain) logs in Spanish (`CAMINO A - fase de ESCRITURA`), and the
  page mirrors `console.log` into `#log`, so a correct run showed Spanish. The
  user-facing strings were translated (comments stay upstream-Spanish for
  provenance); nothing functional changed.
- The stale `pysrv.exe` from the previous day (pre-render server, `H=@HOST@`)
  was replaced with the v39.2 server before deploying.

- **Cold boot verified the same evening** (22:54:46): attempt 1 high-exit at
  t=29, attempt 2 `self-patch` at t=38, `SUCCESS-R00T` t=39, `ROOTCHAN` t=40 -
  the boot hook and AUL relaunch both work on v39.2.
- **`tools/test_all.py --tv` passed 9/9** against a fresh page load (hello,
  kernel image read, normal read, oversized READ refused, cross-page WRITE
  refused, stub alive after each).

- **Gateway tests poisoned the production beacon log** (found while asking why
  AUL seemed to relaunch every ~2 min): the two new v39.2 gateway tests send
  `DSHROOT t=1s start uid=5001`, and `server.py` computed `logs/beacons.log`
  unconditionally, so every test run appended them to the operator's log; they
  then read as a phantom boot. Fixed: `server.py` honours `DSH_LOGS_DIR` (the
  gateway test points it at a temp dir and asserts the production log size did
  not change), `beacons.py` drops a `start uid=` line without `pid=` (which the
  payload always emits) and reports the count, and the 16 already-injected lines
  were moved to `logs/beacons.log.testnoise-2026-10-26`. **There was no AUL
  churn on the TV.**

- **The first live token run was refused - reversed bytes.** The page generated
  the token, wrote it little-endian into the blob, but announced
  `tok.toString(16)` (big-endian hex); the stub's load/store preserves the bytes,
  so the server saw the reverse (`<TOKEN>` vs announced `<TOKEN>`) and refused
  every stub. The page now announces the exact wire bytes (with a
  `test_constants` check), so the announced hex is what PGDB carries. Hardware
  validation was still pending at the end of this session.

- **The vtable trigger was flaky on fresh loads** (`nodeName` stayed `'DIV'`):
  the wrapper address captured before ~20 console lines can be stale after a
  V8 scavenge. The page now re-captures `addrOf(el)` immediately before the
  single `cw`, verifies `wrapper+0x10 == backing`, and retries once; that made
  the live pairing work. This is independent of the token and affects any page
  load that allocates between wrapper capture and the write.
Still pending: one uninstall/`recover.sh` cycle (the undo path).

## 2026-10-26 (third pass) — second code review

An independent re-review (`docs/codreview.md`, kept out of git: it is a review
note, not a repo doc) agreed v39.1 was fit to deploy and found two P1s in
`server.py`, a P2 in the stub's FILE op, a P2 in `Run()`'s tmpfs redirect, and
documentation that had the kernel's memory model wrong. Fixed offline; the
payload is now **v39.2** (`010946ff…`, 33,280 B) and the shellcode blob 7,696 B.
Nothing is hardware-verified (TV still disconnected).

### Server (P1/P2)

- **Every post-peek read is bounded.** The accept loop reset the socket to
  `None` after the 1.5 s peek, so a peer that sent `DSHROOT`/`GET ` and stalled
  could hold the single accept thread (and with it the page, `/deploy.sh`,
  `/save`, beacons and the shell slot). Accept now sets 2 s; `serve_http` keeps
  its 10 s body timeout; the shell branch restores blocking reads only because
  its reader is a dedicated thread; the gateway bounds its hello read.
- **The interactive shell slot can no longer be evicted by a different peer.**
  Two TCP connects used to be enough (send `PGDB`, then open a silent
  connection) to take the operator's shell; now a different peer is refused and
  logged, and the same TV may still replace its own (page reload). The token-less
  `PGDB` handshake remains the open item.
- **`tv_sock` is only aimed at a stub after op5/op7.** Setting it at hello meant
  a keystroke on 9999 could be parsed as the next 16-byte RPC header and desync
  the in-flight operation.
- **`RSET` is matched across split TCP segments** (`RSE` then `T`): one peek
  used to send the client into the 30-minute BUSY wait, in exactly the
  wedged-stub case RSET exists for.
- **`handle_shell` advances `output_dropped`** before clearing the buffer, so a
  shell-log reader at a saved absolute offset no longer silently misses output.
- **`beacons.log` rotates at 16 MiB** (`beacons.log.1`): any LAN peer can append
  a 4 KB line per connection, so the file was a disk-fill vector and a way to
  bury a real boot verdict.
- **The renderer rewrote the template's own guard.** `deploy_script()` replaced
  `@HOST@`/`@WANT@` globally, which turned the guard
  `*@HOST@*|*@WANT@*)` into `*http://<host>*` — a pattern that matches every
  valid render — so the first real deploy refused with `NEED_RENDER`. Found only
  when the TV was finally connected (2026-10-26, first v39.2 deploy attempt);
  the renderer now replaces only the three assignment lines, and the gateway test
  asserts the guard stays literal.

### Stub (P2)

`op_file` ignored `write(2)`'s return, so a short write (ENOSPC on `/opt`)
silently truncated a 4 KB chunk. New `write_full()` loops on partial writes,
retries `EINTR`, reports `-EIO` on a zero write, and op8 sends its status. The
blob was rebuilt and re-embedded (7,600 → 7,696 B); both `--check` modes pass.

### Payload v39.2 (P2 + nits)

- `Run()`'s wrapper now runs `ulimit -f 2048`: the 1 MiB cap bounded only what
  the payload read, while `/tmp` is tmpfs, so a `yes` could fill RAM until the
  120 s kill.
- The first "still waiting on the device" beacon fires at 30 s (it fired at
  ~1 s because the state started at `-30000`); a failed reopen names `_node`
  instead of a hardcoded video40; the scan loop's indentation matches its block;
  the `Kptr` comment now explains VMSPLIT_3G instead of LPAE.
- `payload/global.json` pins SDK 10.0.301 (`latestPatch`): the artifact is
  reproducible only against a known SDK.

### Documentation (actively wrong before this)

- **"ARM32 LPAE" was wrong.** The reference tree's kernel `.config` has
  `# CONFIG_ARM_LPAE is not set`, `CONFIG_VMSPLIT_3G=y`,
  `CONFIG_PAGE_OFFSET=0xC0000000`, `CONFIG_HIGHMEM=y`. The linear map therefore
  covers **lowmem only**; with `PHYS_OFFSET 0x20000000`, `VA = PA + 0xA0000000`
  and `high_memory` at VA `0xE0000000` if lowmem is capped at 512 MiB. A
  pointer at/above that is vmalloc/module space where the subtraction is not a
  translation: a **garbage read**, not a high task/cred. Corrected in
  `AGENTS.md` (§1, §2, traps 5/16), `docs/EXPLOIT.md` (the address-space table
  and the high-half note), `docs/FAILED.md`, `docs/PORTABILITY.md`,
  `README.md`, `docs/TESTING.md` and the `Kptr` comment.
- The high-half item is now two falsifiable checks (read
  `high_memory`/`max_low_pfn`; one deliberate high-PA read against the recon
  claim), not "two causes open".
- `docs/OPEN-ISSUES.md`: removed the stale "update `WANT=`/size" instruction
  (the deploy gate is rendered), added the second review's deferred items, and
  fixed the state block (v39.2, blob size).
- `AGENTS.md` §5 gained `payload/global.json`; `docs/SERVER-HOSTING.md` and
  `SECURITY.md` describe the new server bounds; `.gitignore` ignores `.zcode/`
  (agent scaffolding, not part of the toolkit) and names the 33,280-byte v39.2
  artifact.

### Tools and tests

- `test_constants.py`: a check no longer passes when **both** regexes miss
  (sentinel `None`), and new checks cover the stub caps and `write_full`, the
  payload's `ulimit`/beacon/node fixes, and each server hardening token.
- `test_gateway.py`: stalled beacon sender, split `RSET`, and cross-peer shell
  refusal.
- `root_shell.py` / `run_root.py` / `auto_root.py` reconfigure stdout with
  `errors="replace"` (a TV byte can kill a cp1252 console); `find_task.py`
  closes a desynced reconnect instead of leaking it; `root.ps1` /
  `uninstall.ps1` require IPv4 (TryParse also accepts IPv6), `-DryRun` no longer
  calls a working server "DIFFERENT", and uninstall's manual wait hint is 120 s
  (was 30, while the script needs far longer); `wasm_builder.js` fixes
  `typeof x == "array"` → `Array.isArray`, removes an implicit global `flags`,
  and notes the shared script scope.

All of this is offline: `python tools/test_all.py` → 8/8 layers pass, both
shellcode checks green, two clean builds byte-identical.

## 2026-10-26 (later) — independent review, v39 hardening

A full-repo review (payload, stub, server, tools, scripts, page/WASM, tests, docs)
produced ~60 findings; this batch is the code half, and includes the follow-up
fixes from the review pass itself (§ "Review follow-up (v39.1)" below). **TV was
disconnected**, so nothing here is hardware-verified: the offline suite is green
(sim, gateway, shell, constants, logs, blob↔source↔page) and the on-TV checks are
listed in `docs/OPEN-ISSUES.md` → Pending. Payload v39.1 = `bc05cf51…`, 33,280 B,
reproducible; the shellcode blob is 7,600 B.

### Structural: deploy.sh is a template, rendered per request

The stale `server/deploy_local.sh` (a v37 gate against a v38 payload) broke both
manual deploy and `recover.sh`; the copy existed only because `root.ps1` had to
rewrite `H=`. Replaced the mechanism: `server/deploy.sh` now ships
`H=@HOST@`, `WANT=@WANT@`, `SIZE_WANT=@SIZE@` and `server.py` renders them at
request time from (a) the IPv4 `Host` the TV used and (b) the md5/size of the
`payload.dll` actually served. A static file server leaves the markers in place
and the script refuses with `NEED_RENDER`. Consequences: no generated copy to go
stale, the payload hash can never disagree with the artifact, a non-IPv4 `Host`
is refused with 409 instead of installing a channel that locks the PC out, and
`root.ps1` no longer writes or injects anything (the app-label relabel moved into
`deploy.sh`, where it is a no-op on the 31337 lane).

### Structural: deploy is transactional with rollback

`deploy.sh` used to replace the IL, disable the AOT, and only then write the boot
row — so a failure (or the channel's command timeout) after the swap left the
payload installed, the AOT disabled and **no boot row**: no payload at boot, no
channel, no stock app. Now a `trap` handles EXIT/INT/TERM and the irreversible
steps come last.

- boot row → readback → `aulctl reload` first (harmless while the stock app is
  still in place); the AOT move and the DLL swap after, each rolled back on
  failure (restore the previous DLL from `payload_backup.dll`, re-enable the AOT,
  delete the row) with `ROLLBACK=…` tokens.
- `payload_backup.dll` now really is the DLL that was live before the deploy (it
  used to be a second copy of the new payload, contradicting AGENTS §10).
- AOT-disable failure, a failed `mv`, or a bad installed md5 now aborts —
  `mv … && echo AOT=disabled` was silent, and `COPY=ok` printed before three
  fatal checks.
- the stock-IL snapshot is taken for **any** readable non-payload build, not only
  the retail hash; the old non-retail branch printed `BACKUP_IL=skip` and
  replaced the only stock copy (uninstall then impossible forever).
- `umask 077` + `mktemp -d` for the download, and `cp -p` for snapshots, keep the
  predictable `/tmp` names and the file mode out of play; the DLL is explicitly
  `chmod 0644` before the label check.

`uninstall.sh` mirrors it: relabel **before** `mv` (a relabel failure used to
leave an unreadable stock DLL in `bin/`), refuse a missing DB instead of letting
`sqlite3` create one, `.timeout` on every query, and delete `rootchan.allow`
**last** (it fails closed, so removing it before a step that can fail locked the
channel while the payload was still running).

### Payload v39

- **`Run()`**: 120 s budget (15 s was shorter than the documented deploy waits)
  with output capped at 1 MiB (a `yes`/`cat /dev/zero` filled tmpfs and was then
  read into RAM), a unique temp file per call (auto-update-off now runs on a
  background thread and would have collided on `/tmp/.dsh_cmd.out`), and the
  command passed as an **argument** to `sh -c` instead of spliced into it (a `}`,
  `;` or quote could break the wrapper).
- **Device open** cycles `{video40, video30, video60}` with a per-node errno
  beacon; exclusivity is per instance, so this also removes the payload↔browser
  deadlock. One node was retried 120 times even for `EACCES`/`ENOENT`.
- **`Write32`** splits a page-crossing word byte-wise instead of writing past the
  mapping (the stub already rejected it; the payload did not).
- **Failure paths close the node** (`no kernel image`, `no init_task`, `no task
  offsets`, reopen failure, long-mode idle) — a failed long-mode run held the
  opener for the whole 120 s sleep, blocking the browser lane.
- **`RootChannel` retries a failed bind** instead of falling out to `Exit(0)` and
  discarding a successful root.
- 15 `cand off=` beacons became one `cand n=… offs=…` line (each beacon costs up
  to 500 ms with the PC off); the dead `FindCommNearTail` was removed; the glued
  comment at `ChildParentUid` was fixed.
- Compiled `Host` and the stub's sockaddr are now **TEST-NET placeholders**
  (`192.0.2.1`), not a private LAN IP.

### Stub (physrpc.S) → blob 7,600 B

`op 7` wrote `-c\0<cmd>` with **no terminator**, so a second, shorter command on
the same stub executed the tail of the previous one; `op 8` had the same bug at a
256-byte path. Both buffers are now NUL-terminated with the length clamped to
leave room (511/255), `op 7` rejects a body shorter than `-c\0`, and the stale
`/dev/video40` comment in the `open` block is corrected. Rebuilt, re-embedded and
both `--check` modes are green.

### PC server (server.py)

- **HTTP method gate**: a request line that is not a served method now gets 405.
  Any LAN client sending `PATCH /` used to be treated as the reverse shell and
  took the operator's root-shell slot (proven live with a scratch server).
- **Shell slot is TV-only**: the raw stream is accepted only from a peer that has
  sent `PGDB` or a `DSHROOT` beacon since server start.
- **`PGDB` queue is capped** (8, oldest dropped) — every page load used to leave
  a dead stub socket queued forever.
- **`/save`** refuses a cross-origin POST (Origin vs Host) and still caps at 1 MB;
  beacon lines are capped at 4 KB.
- `deploy.sh`/`deploy_local.sh` are served **rendered** (above).

### Tools

- `physmap.patch_cred` now honours the uid-5001 gate and writes capabilities
  (`root2` used to yield uid 0 **without** CAP_DAC_OVERRIDE); `OFF_INIT_TASK`
  includes `DATA_SHIFT` (it pointed 0x12000 low, so `root2` could never find
  `swapper`); `RAM_HI` defaults to the proven 0x40000000 band (`TVPHYS_HI`
  overrides); a `BUSY`/short hello raises a clear `TimeoutError`; the docstring
  lists ops 6/7/8 and the real page/node; dump output goes to `server/logs/`.
- `kernel_root`: forks **once** and retries the walk (the loop used to fork up to
  12 children, against trap 8); `_sane_cred`'s gid bound matches the payload's
  `SaneCred`; the legacy `root()` no longer prints "uid patch applied" when it
  found only an already-uid-0 cred; the unused `_find_tag_near_tail` is gone.
- `beacons.py` parses the **on-TV marker file** (`--file share/root_boot.txt`
  used to report "no DSHROOT lines"), knows `cred-miss` and the new `open … node`
  / `chan fail … retrying` lines, and says "end of marker file" instead of an
  empty timestamp.
- `tv_rootwatch`: liveness is "the stub served a read", not "init_task is at the
  hardcoded offset" (that RSET a good stub on any other firmware); the server's
  log handles are closed; the cred scan is capped at 8 like the payload's.
- `auto_root`/`run_root`/`write_root`: 508-byte command limit (the stub now needs
  the NUL), `deploy.sh` as the default script (it renders), stale usage/docstrings
  fixed; `root_shell` honours `ROOT_SHELL_TIMEOUT` (the .ps1 wrappers set 180).
- `test_constants.py` (new layer): the same offsets/limits/node names are checked
  across `Program.cs`, `sim_rpc.py`, `kernel_root.py`, `physmap.py`, `physrpc.S`,
  the page and `deploy.sh` — payload/sim drift can no longer pass silently.
- `sim_rpc`: `patch_gate` includes `SaneCred` (the sim rooted memory the payload
  refuses), `high_alloc_probe` emits `cred-miss` and models the 2.5 s sweep
  budget, `high_alloc_gate` mirrors the payload's highCred back-fill; new
  self-tests for each.

### Browser page

- the callback patcher rewrites **the port as well as the IP** (serving on :8080
  dialled :80 and died silently) and **aborts** when served by hostname (the old
  fallback sent the TV to a foreign LAN).
- payload output is bridged into the `#log` textarea, so `/save` finally carries
  `elf_base`/`backing`/`chk`/abort reasons instead of the loader preamble.
- aborts `throw` (the page reports `THREW`, not `RETURNED`); `reserve()` aborts on
  an unexpected exception instead of continuing with a shifted type-id counter;
  the vtable-first gate requires the RELRO segment and 4-byte alignment; the
  shellcode copy is bounds-checked; `_spray`/`_big` are documented as heap
  shaping; the FIRE=false hint no longer names a port nothing listens on.
- `probe.html`: the GC module bytes were malformed (field-count 0 plus two stray
  bytes) so it always said "rejected"; fixed, and the impossible
  `WebAssembly.gc` probe was removed.
- `index.html` retries a failed script load once with a fresh cache-buster.

### Scripts / PowerShell

- `recover.sh`: IPv4-only host, strips any `*://`, fetches the **rendered**
  `deploy.sh` (falls back to rewriting `H=` for a static server), `mktemp` dir,
  and no longer shares one `/tmp/recover.out`.
- `root.ps1`: `-Force` on an already-rooted TV deploys over 31337 (no page load
  needed — a hunting payload may hold every node), host address from
  `Find-NetRoute` with IPv4 validation (the old heuristic could pick the VPN
  adapter), `TvIp`/`HostIp` validated, server child killed on a bind timeout,
  `deploy_local.sh` generation removed.
- `uninstall.ps1`: the server is started **before** the "no channel" message it
  tells you to use; DryRun prints the real command (with the `keep_boot` prefix);
  `Test-TvPort`'s dead `CancelConnectAsync` call removed (the only overload takes
  `SocketAsyncEventArgs`; `Close()` is the real cancel); loopback-only listeners
  no longer count as "server up".
- `run_server.cmd`: `-u`, interpreter/port pre-checks.

### Tests

`tools/test_all.py` gained the constants layer and reports SKIP distinctly
(exit 77) instead of counting a missing `sh` as PASS. Shell tests now cover the
rollback, AOT failure, non-retail snapshot, unrendered template, DB failure,
missing DB and every leftover `uninstall.sh` removes (the old "leftovers removed"
check never created the files). Gateway tests cover the rendered script, the 409,
the 405, the refused stranger and the accepted known peer.

### Docs

`AGENTS.md`, `README.md`, and `docs/{OPEN-ISSUES,LOGGUIDE,TESTING,USAGE,EXPLOIT,PORTABILITY,FAILED,SERVER-HOSTING,SECURITY}.md`
updated for v39, the rendered deploy, `/dev/video30` (stub) vs `/dev/video40`
(payload), the 120 s command budget, `cred-miss`, the new beacons, and the
`PHYS_OFF` (VA−PA delta) vs `PHYS_OFFSET` distinction. Deferred items (per-run
`PGDB` token, per-run task tags, `high_memory`/`max_low_pfn` measurement, OTA
masks, DWARF reader) are listed in `docs/OPEN-ISSUES.md`.

---

### Review follow-up (v39.1) — the reviewer's seven

An independent pass over the v39 batch found three deploy-blockers and four smaller
defects. All are fixed; the payload/stub were rebuilt (v39.1 = `bc05cf51…`,
33,280 B) and the sim/tests extended to cover each.

- **The payload must not leave video40 just because it is busy.** v39 cycled
  `{video40, video30, video60}` one second after any failed open, so a browser
  stub holding video40 pushed the boot payload onto **video30**, whose reads hang
  at phys `0x46000000` while the payload's scans reach `0x60000000`. `OpenDevice`
  now retries the **same** node on EBUSY (the whole budget) and advances only on
  `ENOENT`/`ENODEV`. The v39 beacon also fired once per attempt (the index
  cycles); it now fires on a state change plus one "still waiting" line per 30 s.
- **No capability writes without a uid-5001 ids write.** `physmap.patch_cred`
  returns True for a cred that already reads uid 0, and both `physmap.patch_full`
  and `kernel_root.patch_full` took that as permission to write
  `cap_permitted`/`cap_effective` — which a stale task pointer can aim at init's
  cred. `patch_ids` now reports whether *it* wrote, and caps are written only
  after a write that started from 5001 (`kernel_root.patch_full` uses it; the
  sim has a test that a uid-0 cred's caps stay untouched).
- **`cred-elsewhere` is not a high-half answer.** The low-parent branch scanned
  for the ids pattern and reported the *first* match — the child's own fork-copy
  cred when it was low. The probe and its sim twin now skip the whole child-cred
  object (the pattern repeats every 8 bytes), and the docs/heuristics state the
  real semantics: `at=`/`cred=` are physical, `C=`/`P=` virtual, `verdict=linear`
  means the translated frame was readable, and `cred-elsewhere` says nothing
  about the high half.
- **`root_via_fork` no longer claims success (or sends EXEC) on "already uid 0".**
  That was the stale-task case: a freed `PHYSRPC1` pointing at init's cred hid a
  live stub outside the walked range. It now warns and returns False so the
  caller reloads the page. The legacy non-`--fork` `root()` path had the same
  bug and got the same treatment (it is the path a human runs by hand; `auto_root`
  uses `root_via_fork`).
- **No second landmark.** The loop used to fork again after two misses, and also
  when a fork succeeded but the walk could not find the new `PHYRFORK` - leaving
  the first one paused (trap 8). It now forks exactly once whenever a pid comes
  back: a failed fork (no pid) may be retried, a created-but-unfound landmark ends
  the attempt with "reload the page".
- **`recover.sh`'s static-server fallback rewrites all three markers.** It used
  to rewrite `H=` only, leaving `@WANT@`/`@SIZE@` to exit `NEED_RENDER`; it now
  fetches `payload.dll`, computes md5/size, rewrites all three, refuses if any
  marker survives, and its message no longer overclaims.
- **The `Main` exception path and the channel retry release what they held.** The
  catch slept 20 s holding the physmap node; `RootChannel`'s retry left the
  listener that threw un-`Stop()`ped, so the next bind could fail until the
  socket was collected. Both now clean up first.

---

## 2026-10-26

### Agent-facing logging: beacons.py, LOGGUIDE.md, self-diagnosing tool errors

The log knowledge (what each `DSHROOT` line means, what normal looks like,
what to do next) lived scattered across history docs. Consolidated so the next
agent can decode a boot in one command:

- **`tools/beacons.py`** (new) — beacon-log analyzer: groups `beacons.log`
  into boots on the kernel-uptime reset, splits each boot into AUL launches,
  and prints a verdict per boot (`ROOTED at t=…s` / `NOT rooted - last line: …`)
  plus findings with hints for the known signatures (`HIGH-ALLOC` lottery
  normal-since-v33, `HIGH-SCAN` verdict decoding, `VID40-HELD`, `WIN-OFF`,
  `BIND-FALLBACK`, `STALE-SELFCRED`, `CRASH`, `CHAN-DENY`, auto-update, …).
  `--json` for machines, `--last N` for the recent boots, exit 2 with a
  pysrv/boot-row hint when there is no log at all. Verified against the real
  log: the three 2026-10-25 boots decode to exactly the recorded history
  (fast-exit attempt 1, rooted at t≈35–37).
- **`docs/LOGGUIDE.md`** (new) — the dictionary `beacons.py` points to: every
  beacon line (lifecycle / hunt / patch paths / channel / housekeeping), the
  healthy boot shape, the sick shapes, a tool-error table and the TV-side
  proof files.
- **`root_shell.py` connection failures now diagnose themselves** (exit codes
  unchanged): refused vs. nobody-answered each print a cause-ordered
  checklist pointing at `beacons.log`, the LAN/VPN preconditions and the
  video40 holder case — plus the trap-17 reminder that ping proves nothing.
  A missing `__END__` now says a foreign service or a mid-reply death is the
  likely cause instead of exiting silently.
- **`run_root.py`**: the 509 B refusal now carries the curl-script hint; the
  "no status" path explains op 7's single-use nature and the
  RSET → reload → re-root recovery.
- **`tools/test_logs.py`** (new) + a `logs-and-errors` layer in
  `test_all.py`: fixture logs for the analyzer (boot splitting, verdicts,
  findings, JSON, missing-log hint), offline tests for the new root_shell
  error branches (refused on loopback, black-hole timeout, no-address) and
  the run_root refusal, and a PowerShell parse guard for `root.ps1` /
  `uninstall.ps1` (skipped where PowerShell is absent). Writing the tests
  caught three real bugs before they shipped: the analyzer matched nothing
  on real lines (every line carries the `t=<n>s ` prefix the regexes
  anchored away from), the fast-exit attempt classifier missed the
  `high-alloc … fast-exit` spelling, and the timeout branch was dead on
  Windows (`socket.timeout` arrives with `errno=None` — the winerror
  spellings are handled now).

`docs/TESTING.md` and the `AGENTS.md` files/logs tables updated. Context7 was
not needed: the work is stdlib parsing/sockets.

### Payload v38 — high-scan: the high-half open question is now one measurement

An external review of the pending "high-half read mechanism" item argued the
framing ("video40 pfn-mapping limit vs cache-visibility effect") was the wrong
pair of causes. Checking it against the repo's own evidence confirmed the
review and sharpened it:

- Cache visibility is closed for good: the v28 probe already measured `uid ==
  plain` garbage through two different VA geometries, and a fork-fresh,
  sleeping child's *low* cred reads `cuid=5001` on every boot while a *high*
  one never does — waiting cannot help (v31 measured that too).
- ~~By construction on this kernel …~~ **[retracted same day — see v38.1
  below]** this bullet derived the `0xE0000000`/`0xE0800000` split from a
  stale recon-tree comment; the split was never measured on this TV.
- The review's read of the logs was verbatim-accurate: `parent=e2df7300` stable
  across retries while `cred=b09aa3b5`/`phead=` junk, with the child's own cred
  coherent (`cuid=5001`), is in `server/logs/beacons.log`; and video40
  point-read safety at high phys is established (v28/v35: the 0x46000000 hang
  is the video30 stub; video40 read phys 0x60000000).

`HighAllocProbe` in `payload/Program.cs` (read-only; twin `high_alloc_probe`
in `tools/sim_rpc.py`, self-tested) runs once in the fast-mode gate branch,
right before the unchanged v33 fast-exit:

- Point-reads the translated parent page for `PHYSRPT1` + the child pointer
  (the task itself or `&task->tasks`, the member address children/sibling
  lists store): `verdict=linear` means the page held the parent task — the
  read path returned wrong bytes for a frame it can address.
- Otherwise sweeps proven RAM `0x20000000..0x40000000` (±16 MiB around the
  child's task page, 2.5 s stopwatch): `verdict=elsewhere` (wrong translation;
  `at=` names the true frame and `cuid=` says whether it reads 5001 — which
  would enable a locate-and-patch read path without touching the gate),
  `comm-only` or `miss` (inconclusive; `cov=` states coverage, and coverage
  below `0x40000000` cannot rule out a highmem true frame).
- When the parent is low but the cred is the high object (the 19:00 v32 boot
  shape), the same sweep locates the ids pattern: `cred-elsewhere` /
  `cred-miss`.

Safety bounds: no writes (`Write32`/`PatchCred` untouched); the sweep never
leaves `0x20000000..0x40000000`, the band `LocateInit`/`CredScanNear`/the tail
walks already cover; the translated page (`0x40000000..0x5FFFFFFF`) is only
ever point-read — the exact access the direct-probe `phead=`/`pplain=` lines
have done on every high-allocation boot since v28. Gate, `Kptr` and timings
untouched (trap 16). The twin caught a real bug before deploy: when the
child's cred is itself the high object (`ccred=e2c35300`), the cred-scan
anchor translated above the sweep ceiling and could never sweep — both sides
now fall back to the child's task page.

New artifact: `81b5f5a5…` (31,744 B); `server/deploy.sh` gate updated.

### Payload v38.1 — probe fixed (code review) and the memory-split retracted

A code review of the staged probe found it could never return `linear` or
`elsewhere` on a real boot, and that the docs treated a stale comment as a
measurement. All confirmed and fixed; **do not deploy any earlier v38 build**:

- **Tasks are not page-aligned.** `0xe2df7300` sits at page offset 0x300, so
  the first cut's page+0x400/page+0x3F8 probes and its 0..0x480 page search
  missed every real task — the beacon would always have been
  `verdict=miss`. The probe now works on task addresses: `pc=` reads the comm
  at the translated parent address itself; the sweep finds the comm at any
  offset and derives the task as hit-0x400.
- **The back-pointer member was wrong.** fork() links `&child->sibling`
  into `&parent->children`, not `&child->tasks`. The pontusml DWARF confirms
  children=0x2F8 / sibling=0x300 right beside the TV-measured
  0x2F0/0x2F4/0x3F8/0x400 (and tasks=0x23C matching the walk). A candidate
  parent is accepted only when its children list (next OR prev) contains
  child+0x300, so freed look-alikes fail.
- **A page-edge straddle is covered order-independently.** The first fix used
  an 8-byte carry, but the outward ±step sweep does not visit physically
  adjacent pages consecutively, so the carry lost straddling comms — caught
  by a dedicated fixture (task at page+0xBF8). The search now checks the NUL
  follow-byte at hit+8 with one cross-page byte read on candidate hits only.
- **`cred-elsewhere` beaconed `cuid=unread` forever**: CredUid wants a kernel
  VA and got a physical address. The physical cred is now converted
  (`+PHYS_OFF`) before CredUid, matching the twin. An offset-0..3 ids hit no
  longer abandons the rest of the page (as CredScanNear does).
- **The sim fixtures hid all of it** (page-aligned tasks, an invented 0x2C0
  pointer). The new scenes place tasks at page offset 0x300 with real
  sibling linkage and add the straddle and offset-0 cases; the review
  demanded the old tests fail on that layout, and against the fixed probe
  they do.
- **`0xE0000000`/`0xE0800000` retracted as a measurement.** The split traces
  to a comment in `samsungtv/publish/recon/tvphys.py` that a later revision
  (`samsungtv/recon/tvphys.py`) contradicts; `high_memory` (`c0a2f490` in the
  sim map) was never read on this TV. The pending item is back to the two
  open causes — wrong translation vs video40 wrong bytes — with cache
  visibility still closed. `docs/EXPLOIT.md`, `docs/OPEN-ISSUES.md`,
  `AGENTS.md` §11 and the probe comments now mark the linear map's end as
  unmeasured.
- Unchanged on review's advice: `Kptr`, the v33 fast-exit, every round
  timing; the 2.5 s stopwatch; read-only (no `Write32`/`PatchCred`).

New artifact: `adc2b27c…` (31,744 B); `server/deploy.sh` gate updated
(supersedes `81b5f5a5…`, which never left the repo). `beacons.py`'s
`HIGH-SCAN` hint and the `LOGGUIDE` row updated for the new beacon shape
(`pC=` dropped, `at=` = task address).

### Docs — the v31 "read-reliability" note and the pending item rewritten

`docs/EXPLOIT.md`'s high-half note claimed the failures are "a property of the
read path, not of pointer validity" — unproven, and now phrased as the two
remaining causes with the beacon that decides. `docs/OPEN-ISSUES.md` pending
item 1 is rewritten as that measurement (what fires it, how to read each
verdict, what each verdict would and would not justify).

### root.ps1 / uninstall.ps1 — ICMP is no longer a liveness signal

Deploying v38 was correctly skipped (the TV is off), but the check that
informed it was wrong for an interesting reason: `ping 192.0.2.175`
reported **0% loss** while the PC was not even on the TV's LAN any more
(Ethernet without IPv4, Wi-Fi on 198.51.100.30.x, NordVPN tunnel up) — the tunnel
gateway (198.51.100.1) answers "Destination net unreachable" and Windows
`ping` counts that as a reply (0% loss, exit 0). A proxy-ARP router can
likewise answer for an offline set. Both failure worlds make ICMP useless
here, and `root.ps1`/`uninstall.ps1` still trusted it:

- `Test-TvPort` (both scripts) is now a raw `TcpClient` connect with a 1.5 s
  cap, replacing `Test-NetConnection` (slow on failure, walks its own ICMP
  path). Verified offline: open → true, closed → fast false, off-LAN → false
  in ~1.5 s.
- `root.ps1`'s "TV does not answer ping" warning is replaced by a stock-port
  probe (8001/8002/7676/9197) whose failure message names the actual
  preconditions (PC on the TV's LAN, VPN off) instead of implying ping means
  anything.
- `uninstall.ps1`'s post-reboot "TV came back" wait no longer gates on
  `Test-Connection`: it waits for `Test-StockTv` (a stock Samsung service
  answering TCP) and its timeout message says the decision was made by those
  probes and why ping is not evidence. A negative is honestly inconclusive —
  same exit-2 semantics as before, no false success.

Docs: new trap 17 in `AGENTS.md` §8 and a "do not use ping" note in
`docs/USAGE.md` → Talking to the TV, both recording the 198.51.100.1
signature (0% loss + exit 0 while off-LAN) and the honest alternatives
(TCP probes, fresh `DSHROOT` beacons, `arp -a` having no TV entry).

