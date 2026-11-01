# Testing this toolkit — on this TV and on yours

Several layers, from "runs anywhere" to "needs the TV". `python tools/test_all.py`
runs the offline ones and summarises (the sections below plus the public-release
sanitizer selftest, the list-walk/DWARF fingerprint gate, the AGENTS.md
state-row drift check and the whole-tree hygiene layer); `--tv` adds the
live-stub layer.

```sh
python tools/test_all.py            # offline: no TV, no root, no page
python tools/test_all.py --tv       # + live stub protocol (needs a fresh page load)
python tools/test_all.py --tv --bad-run   # + the op-7 overrun case (kills that stub)
```

Everything below assumes the repo root as the working directory.

## 1. Offline unit tests — `tools/sim_rpc.py`

An in-memory `physmap.RPC` (`MemRPC`) planted with the cred layout measured on the
TV and matched against the DWARF dump of a same-family kernel. It exercises
`kernel_root.patch_full`, `_sane_cred`, the cred-content scanner
(`iter_owner_creds`) and the page-straddle case that a per-page `find()` misses.
It also twins the payload hunt (`hunt_new_phyrfork` + pre-set), the v18
MapPage-vs-kernel alias (`AliasedMemRPC`), per-instance device contention
(`Video40`; two nodes can be open at once), pointers above `0xE0000000` (VMSPLIT_3G + HIGHMEM puts them inside the linear
map, but the video40 read path returns garbage there — the DMA window is the
suspect), and
a hole that must break the scanner's carry. Since v39 `patch_gate` also enforces
`SaneCred`, `high_alloc_probe` emits `cred-miss` and models the 2.5 s sweep
budget, and `high_alloc_gate` mirrors the payload's highCred back-fill.

Since v44 the hunt twin matches the payload's accept rules exactly: `task_pid`
is tri-state (`PID_UNREADABLE` / `PID_OURS` / `PID_NOT_OURS`), `hunt_new_phyrfork`
is ranked (exact tag > pid > prefix, strictly-better-only) and refuses a
readable pid of zero, `hunt_self` mirrors the ranked `self` selection, and a
holed pid page is the model of a true read failure (the only case that keeps the
legacy parent-uid latch). `PROBE_COMM` is a realistic per-run tag built from
`PROBE_PID`, so the twin's own NUL check is at `len(tag)` and not the retired
`hit+8`.

The fifth-pass attempt-1 case (`ReadStaleRPC` + `direct_parent_patch`) is
modelled at the block level: a stale parent task/cred page, the v28 early break
(two pr-0 probes, not four through pr 7), `publish()` rooting, the foreign /
unreadable / stale-0 gate cases, and the v30 process-wide `cred_scan_near`
budget with its offset-0 page case.

This is the layer that catches offset regressions — if `cred.uid` moves, the
self-test fails before anything touches hardware.

## 2. Offline integration — `tools/test_gateway.py`

Starts the real `server/server.py` on scratch ports (`HTTP_PORT`, `RPC_PORT`,
`CTRL_PORT` are env-overridable) and drives it like the tools do: a client waits
for a stub, `RSET` answers immediately, a fake `PGDB` stub pairs, the 12-byte
hello and bytes flow both ways, a second client gets `BUSY`, and an oversized
`POST /save` gets 413.

No TV and no browser. It caught a real bug: a socket timeout left over from the
`RSET` peek detached a just-paired client.

Since 2026-11-01 it also pins the two state bugs the review found: an abandoned
waiting client must release the single client slot (it used to hold it for 30
minutes, so every later tool got `BUSY`), and the beacon-token set must survive
(a) later `/deploy.sh` renders - a *used* token is never evicted, an unused one
older than the last two renders is - and (b) a **server restart**, by stopping
the process and starting a new one on the same ports and the same scratch log
dir. That last check is the live proof of the persisted token file
(`logs/beacon-tokens.json`); without the reload, the running payload's beacons
are refused and never reach `beacons.log`.

## 2b. In-process server checks — `tools/test_server_unit.py`

Imports `server.py` directly (no listener: they start only under `__main__`) and
drives `serve_http`/`_read_full_request` over a socketpair. This is where the
*classes* of request-gate bug are pinned, because a fixture that only names
`server.py` would miss the next leaked file:

- the deny class is **hardcoded** and exercised against a **planted** file in
  lower and upper case (`DENY_SUFFIX`: `.py`, `.pyc`, `.pyo`, `.pyd`, logs,
  `__pycache__`, ...), plus `/logs/...`, `..`, `..%2F`, `%2e%2e` and a docroot
  sibling - all 404, and the planted content never reaches the socket. The
  expected list is a constant in the test on purpose: iterating the module's own
  `DENY_SUFFIX` would silently stop testing an entry the moment it was removed
  (the `.pyc` bug passing its own test); a separate coverage check allows new
  suffixes without editing the list;
- a rendered `/deploy.sh` carries the served artifact's hash/size, a fresh
  token and the host it was fetched from - and still keeps its `@MARKER@` guard;
- the token set's trim + save/reload round-trip (the unit half of the restart
  test above), a corrupt file and malformed rows;
- `log()` never raises when its file is unwritable (it is called from TV reader
  threads; an exception there left `rpc_tv` set with no reader);
- `_client_gone` (live vs closed peer) and the absolute whole-request deadline:
  a partial header must return well under a second, not one timeout per recv.

## 2c. Launcher gate — `tools/test_wait_rooted.py`

`root.ps1` used to accept a bare TCP probe on 31337 as "payload active". After a
deploy the kill is detached, so the dying old app can answer that probe while the
new payload is still hunting - on 2026-11-01 the launcher printed "payload active"
through a five-minute hunt. `tools/wait_rooted.py` replaces the probe: it waits
(1) for the old listener to drop, then (2) for a listener that answers
`id -u` = 0, and exits 3 (rooted, but the port never dropped - the previous DLL
may still be running) separately from 0 and 1.

The layer tests the wait logic offline with an injected port/uid/clock: the normal
drop-then-root sequence, the never-dropping listener, a hunting payload (uid
5001) which must **not** pass, a flapping channel retried until it answers, the
no-listener case (uid never asked), the reply parser, and the CLI contract. It
also asserts that `root.ps1` actually calls the helper and no longer contains the
old "payload active from a port probe" claim - so the launcher cannot silently
regress to the weaker check.

## 3. Offline shell tests — `tools/test_shell.py`

Runs copies of `server/deploy.sh` and `server/uninstall.sh` under a POSIX `sh`
with `/opt/...` and `/tmp/...` redirected into a temp tree, and with stubs for
the TV-only commands (`chsmack`, `sqlite3`, `aulctl`, `curl`, `ls -lZ`, `id`, and
a `cp` that can be told to fail).

It asserts the failure paths that used to be silent:

- a payload with the wrong md5/size is refused and the live DLL is untouched;
- a SMACK label mismatch aborts **before** the rename and removes the temp DLL;
- a boot row that does not read back as 1 aborts without `DEPLOY_DONE`;
- a failed stock snapshot (`BACKUP_IL=fail` / `BACKUP_NI=fail`) aborts before the
  DLL is replaced;
- the stock IL/AOT backups are created when absent, with their md5 recorded;
- `uninstall.sh` refuses to run without a backup, rejects a corrupted one,
  restores and relabels on the happy path, removes the boot row, and aborts on a
  label mismatch instead of printing `UNINSTALL_DONE`;
- **the process-label prelude** — the harness rewrites `/proc/self/attr/current`
  into the temp tree and seeds it with the *browser* label, so both scripts must
  take the app label before touching `bin/` (`RELABEL=ok` + the file content
  checked). This is what makes the documented browser-lane uninstall able to
  write `bin/` at all; an untakeable label must warn and keep going (advisory,
  like `deploy.sh`), not abort.

Needs `sh` (Git Bash on Windows — `TEST_SH=/path/to/sh` overrides).

## Offline retry loop — `tools/test_auto_root.py`

Fakes the RPC and kernel layers: the first root attempt fails, the second
succeeds. It asserts `auto_root` resets the gateway (`RSET`), asks for a fresh
page, retries, and deploys exactly once. This catches the regression that made
`root.ps1` exit when a single-use browser stub died during root. It is part of
`tools/test_all.py`.

## Logging and error paths — `tools/test_logs.py`

Covers the agent-facing diagnostics layer, offline:

- `tools/beacons.py` against fixture logs: boot splitting on the kernel-uptime
  reset, `ROOTED`/`NOT rooted` verdicts, the attempt outcomes (including the
  `high-alloc … fast-exit` lottery shape), signature findings
  (`HIGH-ALLOC`/`HIGH-SCAN`/`OPEN-NODE`/`VID40-HELD`/`WIN-OFF`/`BIND-FALLBACK`/`CRASH`),
  the on-TV **marker file** shape (`--file`, no `DSHROOT` prefix), `cred-miss`,
  the derived `BLIND-WALK` verdict (a long-mode pass that never saw a landmark —
  hint: power-cycle),
  the `--json` shape, and the missing-log hint.
- `root_shell.py` connection failures print the self-diagnosis blocks
  (refused vs. nobody-answered; see trap 17 for why ping is never the check).
- `run_root.py` refuses over-508 B commands with the curl-script hint.
- `root.ps1` / `uninstall.ps1` parse cleanly (skipped where PowerShell is
  absent).

It is part of `tools/test_all.py` (layer `logs-and-errors`); the line
dictionary behind the fixture signatures is `docs/LOGGUIDE.md`.

## 4. Shellcode consistency — `build_physrpc.py --check-embedded`

Assembles `tools/physrpc.S` and compares it byte-for-byte with the `SHELLCODE`
array the page actually runs (`server/payloads/browser_payload.js`), and
`tools/embed_physrpc.py --check` compares that array with
`tools/physrpc_shellcode.bin`. Run both after touching either side
(current size in the `AGENTS.md` state row; it changes with every stub edit):

```sh
python tools/build_physrpc.py                 # physrpc.S -> physrpc_shellcode.bin
python tools/embed_physrpc.py                 # bin -> page (refuses to overflow staging)
python tools/build_physrpc.py --check-embedded
python tools/embed_physrpc.py --check
```

Requires keystone + capstone (`pip install -r tools/requirements.txt`).

## 4b. Constant cross-check — `tools/test_constants.py`

Greps the same numbers out of `payload/Program.cs`, `tools/sim_rpc.py`,
`tools/kernel_root.py`, `tools/physmap.py`, `tools/physrpc.S`, the page and
`server/deploy.sh` and fails on any disagreement: cred/task offsets, caps,
`PHYS_OFF`, the sweep band, `SpanPages`, `MaxPatched`, `MaxSteps`, `BudgetMs`,
the round schedule, the device node list, the callback pattern vs the blob, the
rendered deploy markers, the rollback trap. This is the layer that catches the
failure the other tests cannot see: a green simulator modelling a payload that
has drifted.

## 4c. Debloat tooling — `tools/test_debloat.py`

Runs the five TV-side debloat scripts (`debloat/tools/apply.sh`, `restore.sh`,
`mask.sh`, `unmask.sh`, `q3deps.sh`) under a POSIX `sh` with their absolute TV
paths rewritten into a temp tree and stubs for `pkgcmd`, `sqlite3`, `systemctl`,
`systemd-run` and `dbus-send`, so the assertions are on behaviour (which command
ran, in what order, with what exit code), not on output prose:

- every script refuses to run without a list **file** argument (exit 2, no TV
  command) — the old `${LIST:--}` default was a literal file named `-`, so a
  no-arg or piped run printed `0 of 0` and exited 0; the documented TV form
  `cat script | sh -s <list>` is tested too, and a list piped without the
  argument is refused (exit 2), not silently read as empty;
- `q3deps.sh`: one-unit list → `of 1 checked`; a comment-only list → `FAIL:` +
  exit 2 (never the old `0 coupled of 0 … dependency-safe`);
- `apply.sh`: dry run is a gate (a refused entry fails it), list order, undo
  line before the disable, the canalysis/pisa sentinels (planted, stopped,
  recorded in the undo log, and an unplantable sentinel aborts), denylist,
  injection refusal, sqlite-false stops the batch;
- `restore.sh`: `-A --global` per id, sentinel removal, stop-at-first-failure;
- `mask.sh`: `daemon-reload` before any `stop`/`start`, no start of a unit
  whose mask is ours only, `MISSING` unit names fail the run, all-missing
  exits 2, the persistent `newhome-fix` loop (started once, reported
  `newhome=started` then `active`), the restart-loop check (a listed unit
  still `activating` fails the run; an unrelated one only gets reported; a
  failed `list-units` dump is `loop-check=failed` and fails the run rather
  than reading as "no loops"), and
  the kill pass kills the process whose `/proc/<pid>/exe` is the
  listed binary (POSIX only — the fixture points `PROCDIR` at a fake tree);
- list hygiene (bare ids, no denylist entry, the 29-unit mask-list lock and
  the 23-binary kill-list lock, with the OTA-stack names asserted by name -
  services, timers and paths alike - plus the batch-3 list lock: exactly
  the 22 voice ids, and the reverted sharing ids must not reappear as
  active lines) and `merge.js`
  determinism: regenerating the inventory from the committed registry dump may
  flip only the two documented overrides, with matching counts and summary.

`sh` is required; on Windows the layer finds Git Bash
(`C:/Program Files/Git/bin/sh.exe`) even when it is not on `PATH`, and only
reports `SKIP` (exit 77, shown as `SKIP` — not `PASS` — by `test_all.py`) when
there is no `sh` at all.
Part of `tools/test_all.py` (layer `debloat-tooling`).

**Git Bash's `sh` is bash, and the TV runs busybox ash** — two POSIX rules
differ and have already hidden real bugs (2026-10-31 review):
`:` is a *special builtin*, so `if : > "$file"; then … else … fi` terminates the
shell on a redirection error before the `else` runs (the scripts now use
`if ( : > "$file" )`, and `test_debloat` locks that form), and a failed
*compound-command* redirection is not fatal (the undo-log writes are now
`printf` simple commands whose status is tested). A runtime case that fails for
both shells is in the suite; when touching any TV-side script, also run it under
real ash (`wsl -e sh`, or a Linux host) before trusting a green Git Bash run.

## 4d. Whole-tree hygiene — `tools/test_hygiene.py`

The layers above only cover code somebody wrote a fixture for. This one covers
the classes that no fixture catches:

- **every `.py` in the tree compiles** — not just the imported ones: a tool no
  test imports (`find_pidns.py`, `taskwalk.py`, a `__main__` block) can rot for
  weeks after a refactor;
- **every tracked `.json` parses** (`docs/state.json` feeds AGENTS.md, the
  debloat inventory feeds the lists);
- **every TV-side `.sh` is byte-clean**: no CR (busybox reads it as part of the
  token: `#!/bin/sh^M: not found`), no UTF-8 BOM (breaks the shebang), starts
  with `#!`, and parses under `sh -n` without executing anything. This replaces
  the old ad-hoc LF check for four files with the whole set;
- **`.gitattributes` still pins `*.sh`/`*.py` to LF** - a lost rule only bites on
  the *next* checkout (Windows rewrites the scripts to CRLF and the TV cannot
  run them), so it is checked as part of the same class;
- the committed shellcode blob is non-empty and the runtime dirs are in
  `.gitignore` (the single source of truth for tracked vs ignored).

## 5. Live stub protocol — `tools/test_stub.py`

Needs the TV browser on the exploit page (a fresh load = a fresh stub) and the
port-80 server up. It checks the wire contract the PC tools rely on: sane hello,
kernel Image readable, normal read/write, an over-long READ refused with -EINVAL
while the stub keeps serving, a cross-page WRITE refused, and (with `--bad-run`)
an over-long op 7 that is refused and ends the stub instead of parsing the
leftover bytes as a header.

A stub is single-use: after `--bad-run`, or after an op 5/7/8, reload the page.

## On the TV — the checks that need hardware

Run these once per payload change (`AGENTS.md` §7 has the canonical list):

1. `python tools/root_shell.py "id" <tv-ip>` → `uid=0(root)`.
2. `python tools/root_shell.py "grep CapEff /proc/self/status" <tv-ip>` →
   `0000003fffffffff`.
3. `python tools/root_shell.py "md5sum <bin>/MultiControlService.dll" <tv-ip>` →
   the md5 of `server/payload.dll` (the `AGENTS.md` state row is the single
   source). The deploy gate is rendered from that file, so there is no constant
   in the scripts to compare.
4. Cold boot (mains unplug, not the remote) with the browser closed → 31337 is
   back within ~60–90 s; `logs/beacons.log` shows `DSHROOT` chain.
5. `python tools/test_all.py --tv` against a fresh page load.

## Porting to another Tizen TV

The suite is written to be pointed at a different set, not just re-run:

1. Re-measure the target facts in `AGENTS.md` §2 (Image base, `init_task`,
   task-list offset, cred offsets) and update `payload/Program.cs`,
   `tools/kernel_root.py`, `tools/physmap.py` and the payload.
2. Put your PC's IP into `tools/physrpc.S` (the `sa` word), rebuild, re-embed,
   and re-run the two consistency checks.
3. Nothing to edit for the deploy gate: `server.py` renders `WANT=`/`SIZE_WANT=`/
   `TOKEN=` per request from the `payload.dll` it serves — just copy your build
   over `server/payload.dll`.
4. The device node matters: the shipped stub opens `/dev/video30`; if your set
   only exposes another node, change `physrpc.S`'s `path:` and rebuild.
5. Run `python tools/test_all.py` first (it should be green before any hardware),
   then the on-TV list above.
