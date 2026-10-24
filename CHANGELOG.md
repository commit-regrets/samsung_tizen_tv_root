# Changelog

All notable changes to this toolkit, newest first. Dates are day-level and times
are deliberately omitted — the *why* of a change belongs here, the *how* belongs
in `docs/`.

**Maintenance rule:** every change to the scripts, payload, server or docs gets an
entry here, under `Unreleased` if it is not part of a dated batch. A change with no
entry is an incomplete change. `AGENTS.md` repeats this rule for agents.

---

## 2026-10-24

Worked through `docs/OPEN-ISSUES.md` (triaged from the 2026-10-23 code review).
PC-side items were verified offline; the payload change is **built and staged, not
yet deployed** (the TV's channel went down before the deploy — see the end of this
entry).

### Added

- `tools/test_gateway.py` — integration test for the port-80 RPC gateway: starts
  `server.py` on scratch ports, proves `RSET` answers while a client is still
  waiting for a stub, that the waiting client survives it and receives the 12-byte
  hello from the next fake stub, that bytes flow both ways, that a second client
  gets `BUSY`, and that an oversized `POST /save` gets 413. It found a real bug on
  its first run (see *Fixed*).
- `tools/kernel_root.iter_owner_creds()` — the owner-cred content scan as one
  page-straddle-safe generator, now used by `scan_cred.py` and
  `tv_rootwatch.root_by_cred_scan` instead of two copies of a per-page
  `data.find()` that could never see a 32-byte pattern split across pages.
- `tools/build_physrpc.py --check-embedded` — compares `physrpc.S` with the
  `SHELLCODE` the page actually runs (byte-identical with keystone; literals-only
  fallback without it). It exists because the two had drifted.
- `tools/smack_relabel.py`: `CRED_SECURITY` and `sane_smack_blob()`, so
  `tools/find_task.py` no longer imports the reference tree's `smack_borrow`.

### Changed

- **Payload v14** (23,040 B, md5 `5b798012ae35c9c567fa7a5ea91d6683`):
  - `Beacon()` caps the connect at 500 ms. Every beacon was a blocking
    `TcpClient.Connect`; a stale `rootchan.host` could burn the ~40 s boot budget
    in SYN retries, contradicting "root at boot with no PC".
  - fork children close `/dev/video40` (`syscall(6, _fd, …)`) before sleeping, and
    the fast-exit path closes it before `Environment.Exit`. Previously each failed
    round left a child holding the single RDWR opener for 120 s, so the next AUL
    launch sat in the `open()` retry (a slow-boot cause that looked like a failed
    round). Children are also reaped with `waitpid(pid, WNOHANG)` — exact pids, so
    .NET's own `Process.Start` children are never stolen.
  - `Serve()` sets 30 s read/write timeouts, caps a command line at 4 KB and
    pending input at 8 KB. The channel serves one client at a time, so one silent
    or half-open connection used to own 31337 until the app restarted.
  - `PatchCred()` validates the cred first (`SaneCred`: physical range, aligned,
    `usage <= 0x10000`, plausible ids) — the analogue of Python's `_sane_cred`. A
    bogus `real_parent` that looked like a kernel pointer could patch a foreign
    cred (init's included).
  - The 31337 allowlist fails closed: a missing/unreadable `rootchan.allow` denies
    instead of allowing everyone. `deploy.sh` now writes that file before the DLL,
    so an interrupted deploy cannot leave an open root channel. A hand-copied
    payload needs the file too (`AGENTS.md` §1).
  - `TrySelfUpdate()` requires an MZ/PE image and keeps the previous DLL as
    `MultiControlService.dll.prev`; any `share/next.dll` over 1 KB used to replace
    the payload with no check and no rollback.
  - `MapPage()` `munmap`s when it evicts the cache (it used to `Pages.Clear()` and
    leak every mapping), and the `mmap2` fallback treats only `-errno` values
    (`-4095..-1`) as failures — a successful mapping in the top half of the
    address space is a negative int32. The `mmap64` `== -1` check was left alone
    (that half of the review finding was wrong).
- `server/server.py`:
  - The RPC gateway claims the client slot under `rpc_lock`, then **releases the
    lock before `rpc_queue.get(1800)`**. Holding it across the wait froze `RSET`,
    the TV forwarder and every later client for as long as no page was open —
    which is the normal flow, since `auto_root.py` connects first.
  - `CTRL_PORT`/`RPC_PORT` can be overridden from the environment (needed by the
    new test), `POST /save` bodies are capped at 1 MB (413 beyond), and the shell
    bookkeeping no longer leaks: `tv_sock` is cleared when the shell closes, the
    output buffer is trimmed to 1 MB with an absolute position so a client cannot
    lose output after a clear, and `rpc_tv_reader` uses the same trim.
  - The `RSET` peek timeout is 0.5 s and is now always cleared afterwards.
- `server/deploy.sh`: fail loud and snapshot the stock app.
  - `DLL_LABEL_MISMATCH`, `BOOT_ROW_WARN` and `AUL_RELOAD=fail` now `exit 1`
    (`auto_root.py` only checks the output tokens, so a warning used to be
    reported as a verified deploy).
  - The label is set and **verified on `$D.tmp` before it replaces the live DLL**;
    aborting after the rename would have left the app unable to start (the
    2026-10-22 regression).
  - `share/mcs_orig.dll` / `mcs_ni_orig.dll` are created from a *known-stock*
    file when they are absent (md5-gated, with the md5 recorded in
    `mcs_orig.md5`/`mcs_ni_orig.md5`), because `uninstall.sh` hard-failed without
    them and no script had ever created them.
  - `rootchan.allow` is written before the DLL; `WANT=`/`SIZE_WANT=` are named
    constants.
- `server/uninstall.sh`: accepts a backup whose md5 matches the recorded
  snapshot (a non-retail TV can still uninstall), and a `LABEL_WARN` now aborts
  instead of printing `UNINSTALL_DONE`.
- `server/recover.sh`: prefers `deploy_local.sh`, otherwise rewrites `H=` inside
  the fetched `deploy.sh`; aborts (and says so) unless the deploy prints
  `DEPLOY_DONE`; the verify hint names `root_shell.py` instead of the non-existent
  `chan.py`.
- `tools/root_shell.py`: accepts `ROOT_TV` as well as `TV_IP` (the `.ps1`
  wrappers only set `ROOT_TV`), returns non-zero on a connection or protocol
  failure, and its docstring no longer says `chan.py`.
- `root.ps1` / `uninstall.ps1`: pass `$TvIp` to `root_shell.py` and check its exit
  code — the bare form exited 2, and `root.ps1` printed "Permanent root is up"
  without the check ever running. `uninstall.ps1` also declares `-NoServer`, adds
  the process-name check to `Stop-ToolkitServer`, and watches 31337 for the whole
  boot budget instead of 20 s (a still-booting payload could be reported gone).
- `root.ps1` no longer claims persistence it did not observe: it says plainly that
  `deploy.sh` restarted the app, so an open 31337 proves the payload runs, not
  that it starts at boot.
- `tools/run_root.py` / `auto_root.py` refuse commands over 509 B and
  `write_root.py` enforces 255 B paths / 4 KB chunks: the stub's `cmdbuf` is 512 B
  and it trusts the header, so a long command scribbled over adjacent stub data.
- `tools/tv_rootwatch.py`: finds an interpreter from `TVWATCH_PYSRV`/`PATH`
  instead of requiring the author's `pysrv.exe`, and loop mode now keeps watching
  after a successful `op 5` (it used to return 0 unless `--no-shell`).
- `tools/physmap.py`: the dead `root`/`rootexec` modes and `full_root()` are gone.
  They called an undefined `find_tasks_offset`/`walk_tasks`, required a firmware
  `uImage` that is not in the repo, and gated creds at `0xD0000000` while claiming
  success. `verify` no longer touches the uImage.
- `tools/physrpc.S` opens `/dev/video30`, matching the shipped blob. The source
  said `/dev/video40`, so a rebuild + re-embed would have silently switched device
  nodes; `--check-embedded` now catches that drift.
- `tools/smack_relabel.py` / `tools/find_task.py`: no hardcoded author paths,
  `find_task.py` defaults to the real comm (`DN_trol-Service`) and runs from a
  clone; both are labelled diagnostics (the supported path to the app label is the
  app's own channel).
- `tools/_selfroot.py` and `tools/taskwalk.py` are labelled DIAGNOSTIC, including
  the fact that `taskwalk`'s "next" is a guess, not a validated link.
- Docs: `AGENTS.md` v14 size/md5, the new channel-hardening facts, the payload
  invariants (close the fd in the child, `Sleep(700)`, `SaneCred`), the 509 B
  command limit, and `root_shell.py <TV_IP>` in every example; `README.md` payload
  row; `docs/SCRIPT-REVIEW.md` no longer claims `find_task.py` cannot run.

### Fixed

- **`root_via_fork` patched a freed task's cred pointer.** It looked up only the
  first `PHYSRPC1` task on `init.tasks.prev`; after an earlier page load that can
  be a dead thread, so the sane-cred check rejected its cred pointer six times
  (`skip 0xe234cf00 (not a cred)`) while the live stub sat further along the same
  list — the browser lane could not root at all. It now collects every tagged
  task (`_find_tags_near_tail`) and patches whichever validates;
  `tv_rootwatch.root_by_tail` got the same fix. Proven on a fresh stub: the live
  task was found on attempt 1 and patched immediately.
- **The gateway dropped a client that had just been paired.** The `RSET` peek set
  a 0.5 s socket timeout and only cleared it on success, so the timeout survived
  into the forwarding loop and the first idle read raised `socket.timeout` — the
  client was detached, `rpc_client` cleared, and the next client got the cached
  hello instead of `BUSY`. Caught by `tools/test_gateway.py`.
- `kernel_root.patch_full`'s uid readback (already fixed on 2026-10-23) is now
  covered by the extended `sim_rpc.py` self-test, together with the page-straddle
  case for the real scan generator.

### Deployed and verified on the TV

- `server/payload.dll` v14 deployed over 31337 at 15:09 (`SIZE=23040`, md5 match,
  `DLL_LABEL` verified, `BOOT_ROW_COUNT=1`, `AUL_RELOAD=ok`, `DEPLOY_DONE`).
- Cold boot verified with `systemctl --force reboot` from the root channel: the TV
  left the LAN, came back at +27 s and **31337 was open at +53 s** with v14
  (`uid=0`, `CapEff=0000003fffffffff`, DLL md5 `5b798012…`, app label correct).
  The boot beacon chain shows attempt 1 fast-exiting and attempt 2 rooting, as
  designed.
- Channel hardening proven on hardware: a 5,005-byte command line is rejected with
  `ERR command too long (5005 > 4096)`, and a silent client is dropped at 30 s
  while the next client is served at 31.3 s.
- **The real reason the TV looked unreachable:** Windows firewall has inbound
  *Block* rules for `python.exe`; the server had been started with `python
  server.py`, so the TV could not fetch the page and no beacon ever arrived, while
  the server looked healthy from the PC. Running it as `pysrv.exe` (the interpreter
  `root.ps1` already prefers) fixed both. This is now written down in
  `docs/OPEN-ISSUES.md` and `AGENTS.md` §1.
- Still open from the review list: binding 31337 to one address (`AGENTS.md` §11).
  Everything else was closed later the same day (below).

### Uninstall, backup creation and recovery — verified on the TV

- `uninstall.ps1 -NoWait` ran end-to-end: stock IL `f61f60dd…` and AOT
  `6c9bdcc4…` restored and relabelled, `BOOT_ROW=removed remain=0`,
  `UNINSTALL_DONE`, exit 0. It also demonstrated the fail-closed allowlist (#12):
  `uninstall.sh` deletes `rootchan.allow`, so the still-resident payload refused
  every later connection — correct behaviour, but it makes uninstall a one-way
  door until the next boot or a page load.
- With the stock IL/AOT back on disk and the backups deleted, the next deploy
  created them from scratch: `BACKUP_IL=ok`, `BACKUP_NI=ok`, md5s exactly
  `f61f60dd…`/`6c9bdcc4…`, recorded in `mcs_orig.md5`/`mcs_ni_orig.md5` (#3).
- `recover.sh` ran from the root channel: `RECOVER=deploy_local.sh` → deploy →
  `DEPLOY_DONE` → `RECOVER_DONE` (#5).
- A fresh browser page then rooted the stub and redeployed (the #4/browser path),
  and the final **mains power-cycle** boot confirmed v14 again: payload start
  20:23:41 → `SUCCESS-R00T` 20:24:05, channel up, `uid=0`, full caps.
- **Do not reboot the TV with `systemctl --force reboot` from the payload.** The
  first one worked; the second left the set in a deep standby that the remote
  could not wake, and only unplugging it from the wall brought it back. Ask for a
  power cycle instead (also recorded in `AGENTS.md` and `OPEN-ISSUES.md`).

### Stub hardening (#10/M3) and a test suite for other TVs

- **`tools/physrpc.S` now clamps everything the client controls.** READ requires
  `offset < 0x1000` and `offset+len <= 0x1000`; WRITE32 requires
  `offset <= 0xFFC`; READMANY caps the batch at 32768 pages; RUN caps the command
  at the 512-byte `cmdbuf`; FILE caps path 256 / data 4096. A refusal returns
  `-EINVAL`; for the two ops whose payload is already in the socket (RUN, FILE)
  the stub then exits, because parsing those leftover bytes as the next header is
  how a malformed request would otherwise turn into a corrupt write. The other
  three keep serving (no payload follows).
- Blob rebuilt 7440 → **7552 B**. Re-embedding is no longer a manual step:
  `tools/embed_physrpc.py` writes the array into `browser_payload.js` (refusing a
  staging overflow; `--check` proves page == blob), and
  `build_physrpc.py --check-embedded` proves blob == `physrpc.S`. Both pass
  byte-identical (`tools/physrpc_shellcode.bin` is committed so the check works
  without keystone).
- **Live-verified on the TV** (`tools/test_stub.py`): oversized READ refused with
  `-22` and the stub kept serving, cross-page WRITE refused with `-22`, overlong
  op 7 refused with `-22` and the stub ended; then `kernel_root.py --fork` rooted
  the same hardened stub and its op-7 shell returned `uid=0` with full caps.
- Tests for other TVs:
  - `tools/test_shell.py` — 17 dry checks of `deploy.sh`/`uninstall.sh` under
    `sh` with stubbed `chsmack`/`sqlite3`/`aulctl`/`curl`/`ls -lZ`/`id`: bad
    payload refused, label mismatch aborts before the rename and leaves the DLL
    intact, bad boot row aborts, stock backups created with md5 recorded,
    uninstall refuses missing/corrupt backups, restores + relabels, removes the
    boot row, aborts on label mismatch.
  - `tools/test_stub.py` — the live wire-contract + clamp layer.
  - `tools/test_all.py` — runs every layer; `--tv` adds the live stub;
    `docs/TESTING.md` documents each layer and how to port the suite.
- `tools/tv_ws_launch.py` — the Samsung remote-control WebSocket probe/launcher
  from the research tree, adapted into `tools/` (token under `server/logs/`,
  `--secure` for 8002). Its docstring records the measured result on this unit:
  `ms.channel.unauthorized` with or without the old token, so it is a diagnostic
  and a launcher for other sets, not a way in here.
- `tools/requirements.txt` gains `websocket-client`; `AGENTS.md` §5/§7/§11 and
  `docs/OPEN-ISSUES.md` point at the new suite.

### Second-pass review leftovers (PC-side)

An independent re-read of the landed fixes found four leftovers. Three are PC-only
and fixed here; the fourth needs a payload rebuild.

- **`tv_rootwatch.root_by_tail` could short-circuit on a stale tag.** It walked
  every `PHYSRPC1` task but returned `"already"` as soon as *any* of them had a
  uid-0 cred — a freed task's cred pointer can land on init's, or on a cred a
  previous run patched, and that hid a live uid-5001 stub. It now writes only a
  uid-5001 cred, remembers uid-0 tags without stopping, and reports `"already"`
  only when no uid-5001 cred exists. This is the watchdog twin of the
  `root_via_fork` first-hit bug; `tools/sim_rpc.py` grew two cases for it
  (stale-uid-0 tag → `"rooted"`, second pass → `"already"`).
- **`deploy.sh` did not abort when the stock snapshot failed.** `BACKUP_IL=fail` /
  `BACKUP_NI=fail` were warnings, so a failed `cp` could continue to `COPY=ok` /
  `DEPLOY_DONE` and re-open the "uninstall has no backup" hole the snapshot was
  added to close. Both now `exit 1` *before* the DLL is replaced, and
  `tools/test_shell.py` gained four checks (IL and NI snapshot failure: abort + the
  live DLL stays stock) using a `cp` stub that fails on demand.
- **`tools/_selfroot.py`** (diagnostic) now uses the multi-tag walk and only
  patches uid-5001 creds, matching the supported paths.
- **`SaneCred` still accepts uid 0** — `kernel_root._sane_cred` is a pointer
  validator, and the payload's call sites patch a cred whose uid is 0 *or* 5001,
  so a bogus `real_parent` that landed on init's cred would still be written (a
  near-no-op, but not ours). Closed properly in v15, below.

### Payload v15 — M4 closed, deployed and boot-verified

- `PatchCred` now refuses any cred whose uid is not **5001**, at the single choke
  point every call site goes through; a uid-0 cred counts as "already done" and
  is never written. `SaneCred` stays the pointer-shape check (range, alignment,
  usage, ids). The five call sites (`self`, `direct-parent`, the child-pointer
  scan) now only ask for uid 5001, so a bogus `real_parent`/`parent` landing on
  init's cred can no longer be patched. Same size, new md5:
  **v15, 23,040 B, `bf0c0342437c236c20ecaa0a8ee3bf4c`**.
- Deployed over 31337 (label verified, `COPY=ok`, `BOOT_ROW_COUNT=1`,
  `AUL_RELOAD=ok`, `DEPLOY_DONE`). Loaded with the documented `kill -9` path: AUL
  respawned the app in ~32 s, the beacon chain shows `direct-patch uid=0` (so the
  uid gate accepted the real cred and the patch still works).
- **Cold boot after a mains unplug**: round 0 fast-failed, round 1 rooted
  (`SUCCESS-R00T`, `ROOTCHAN 31337`) within ~33 s of the first probe;
  `uid=0`, `CapEff=0000003fffffffff`, DLL md5 `bf0c0342…`, boot row intact.
- `deploy.sh`'s `WANT=`/`SIZE_WANT=` and `AGENTS.md` §1/§7, `README.md` and
  `docs/OPEN-ISSUES.md` now carry v15.

### Payload v16 — 31337 binds one address, and the last item closes

- The listener no longer binds `0.0.0.0`. `RootChannel` derives the TV's own
  address from the **route to the recorded PC** (a UDP `connect` that sends no
  packets) and binds that. No IP is hardcoded, so another person's laptop needs no
  change: whichever address `deploy.sh` records is the one the bind follows. A
  wildcard listener was reachable from Wi-Fi Direct/tethering even though
  `PeerAllowed` filtered the peer; this keeps it off those interfaces.
- It **re-derives the address every 30 s** and rebinds if it moved (the accept
  loop polls `Pending()` so the check can run between accepts) — the failure mode
  a fixed bind would have had on a TV that changes address. With no route yet
  (TV offline at payload start) it falls back to `Any` and beacons
  `chan bind … failed`, then moves to the real address when one appears.
- Same behaviour otherwise. New size/hash: **v16, 24,064 B,
  `ef8721881df2903f36371aaa482eed9f`**.
- Live verification: after a `kill -9` reload and again after a mains cold boot,
  the beacon reads `ROOTCHAN 31337 uid=0 bind=192.168.178.175` and
  `/proc/net/tcp` shows `AFB2A8C0:7A69` LISTEN (192.168.178.175:31337), **not**
  `00000000:7A69`; `uid=0`, `CapEff=0000003fffffffff`, md5 match, boot row intact.

---

## 2026-10-23

An independent code review landed: `tools/sim_rpc.py` plus a `patch_full` fix, the
triaged work list in `docs/OPEN-ISSUES.md`, and the repo hygiene below.

### Added

- `tools/sim_rpc.py` — in-memory physmap RPC (read/write32/readmany) so
  `kernel_root.patch_full`, `_sane_cred` and the owner-cred scan pattern can be
  exercised without a TV. The research QEMU kernel never reached userspace, so
  this is the offline stand-in; `python tools/sim_rpc.py` is the self-test.
  Layout constants match the TV and the pontusml DWARF dump (`cred.uid +4`,
  `cap_inheritable +0x28`).
- `CHANGELOG.md` (this file), plus a rule in `AGENTS.md`: any future change must be
  recorded here with its reasoning. The dated narrative that had accumulated in
  `AGENTS.md` and the docs now lives here; those files describe the current state and
  the how, not the history.

### Changed

- `AGENTS.md` gained a "Maintaining this repo" section defining that split, and the
  narrative history paragraph became a pointer to this file.
- `README.md` documentation index lists the changelog.

### Fixed

- `kernel_root.patch_full` verified uid by reading `cred+40` (`cap_inheritable`)
  instead of `cred+4`. The ids and caps were already patched; a non-zero
  inheritable made `--fork`, `tv_rootwatch.py` and `scan_cred.py --patch`
  report failure and skip the shell. Readback now uses uid at +4 and the
  named cap offsets.
- **`server/index.html` was the pre-fix copy.** The service-worker unregister, the
  dynamic `?v=` cache key and the `RUNNING_AT` marker existed only in the working
  tree used for testing; the shipped file still loaded
  `lib/wasm_builder.js?v=5`. The tested page is now in the repo (this is the bug
  that once made the TV run a stale builder and die before logging).
- **Repo hygiene:** `payload/out10`–`out13` (16 build artifacts, ~690 KB) were
  committed by accident; they are untracked again and `payload/out*/` is ignored
  (only `server/payload.dll` is tracked). Stale constants fixed: `AGENTS.md` said
  payload "v7", 36 files and `SIZE=17920`/`d247e67a…`; `.gitignore` said 18 KB;
  `docs/SCRIPT-REVIEW.md` and `docs/PORTABILITY.md` implied
  `smack_borrow.py`/`dwarf_offsets.py` ship in `tools/` (they do not).
---

## 2026-10-22

The day the mechanism was proven, broken, and proven again — and the repo was made
readable.

### Added

- **Host-independent operation (v10).** The toolkit no longer assumes the author's
  LAN:
  - the exploit page **rewrites the shellcode's callback address at runtime** from
    `location.hostname`, so the browser stage connects back to whichever PC served
    the page (no rebuild needed);
  - `deploy.sh` records the PC address in `share/rootchan.host`, and the payload
    (v10) reads beacons' destination from it, falling back to the compiled-in
    default;
  - `server/recover.sh` takes the PC address from that file (or an explicit
    argument) instead of a hardcoded default;
  - `tools/root_shell.py` requires a TV address (`argument` or `TV_IP`) rather than
    silently using the author's.
  Payload v10: 20,480 B, md5 `e45e53b6e20925521dee954ec2a1d1d8`. Verified: booted
  and rooted (71 s on that boot, via the direct-parent path), beacons reached the
  PC, `rootchan.host` present.

- **Persistent root, twice over.** The boot payload roots the TV at every boot and
  serves a command channel on TCP 31337. It was achieved with payload v5, re-verified
  after a boot regression with v7, and made fast with v9 (~40 s from power-on, with
  no PC or browser involved). After the payload was removed to test the undo path it
  was reinstalled and verified again on a cold boot.
- **`server/recover.sh`** — one command, run from a root shell on the TV, that takes
  the app's SMACK label and reinstalls the payload end to end.
- **`docs/SERVER-HOSTING.md`** — how the PC-side server must run, and the silent-death
  trap described below.
- **`docs/PORTABILITY.md`** — the four gates for another Tizen 9 TV: browser, physmap,
  kernel constants, on-boot carrier; what to re-measure and what transfers unchanged.
- **`docs/USAGE.md`** — the operational detail that used to clutter the README:
  options, the two TV-side steps, expected output, host-IP caveat, uninstall
  behaviour, manual fallback, common failures.
- **`server/probe.html`** — a zero-risk probe for a foreign unit: reports the user
  agent, Chrome version and real WasmGC support (it validates a struct-type module),
  and executes nothing.
- **`tools/dwarf_offsets.py`** — reads struct offsets from a kernel build's DWARF.
  Four of the offsets it produced matched the TV exactly (`comm +0x400`,
  `cred +0x3F8`, `real_parent +0x2F0`, `tasks +0x23C`), which is what made it a
  trustworthy layout source.
- **`tools/find_task.py`** — resumable physical scan for a task comm; reconnects and
  continues after a desynced batch instead of restarting.
- **`tools/tv_rootwatch.py`** — host watchdog: starts the server if needed, roots the
  exploit stub, and hands back a root shell on `127.0.0.1:9999`.
- **`tools/smack_relabel.py`, `tools/smack_borrow.py`** — the kernel-memory label
  approach, kept because the diagnosis is instructive even though it was not needed.

### Changed

- **Docs reviewed one by one and repaired.** `docs/BOOT-REGRESSION-SMACK.md` was
  corrupt (an earlier edit had spliced a correction note and PowerShell fragments
  into the middle of a sentence) and was rewritten. `docs/FAILED.md` had three
  overlapping SMACK sections, now one that tells the story in order. `docs/SCRIPT-REVIEW.md`
  had become a second changelog, so it is now an actual review of the scripts (issue
  table, race status, limitations, validation). `docs/SERVER-HOSTING.md` pointed at
  paths that were not in this repo, so `server/run_server.cmd` and
  `server/run_server.vbs` now exist here, and the interpreter is configurable via
  `TV_PY`. `AGENTS.md` §1 was the same story twice plus payload lineage; it is now a
  compact current-state section, and §10/§11 lost two factual errors and a duplicated
  analysis.
- `docs/EXPLOIT.md`: the address-space paragraph was wrong (it claimed the linear map
  covers up to `0xFFFFFFFF`), which is exactly the trap that made a vmalloc label
  lookup look like "not found". It now separates the linear map from vmalloc and says
  why the physmap can only translate the former.
- **README rewritten for readers** (265 → ~140 lines): what the project is, current
  state, quick start, four-line summary of the chain, documentation index, layout,
  requirements, compatibility, safety. The deep content moved into `docs/`.
- **`root.ps1` now injects a relabel prelude** into the generated `deploy_local.sh`.
  Without it the automated path deployed from the browser-labelled stub, whose SMACK
  label cannot write the app's `bin/`, so it always ended in `COPY=fail`.
- **`deploy.sh` restarts the app detached** — `aulctl stop` blocks while the payload
  is running (it waits for the app to exit), so the script used to hang before
  `DEPLOY_DONE`. It now runs `( sleep 1; stop; sleep 3; start ) &`.
- **The server runs as a scheduled task** (`TV-LabServer`) launched through `wscript`,
  so no console owns it.
- **The deploy and uninstall scripts verify their SQL** instead of trusting it: they
  read `boot_sequence` back (`BOOT_ROW_COUNT=1`, `remain=0`) and fail loudly.
- **Documentation rewritten for timelessness**: prose no longer carries timestamps;
  the history is this file.

### Fixed

- **Payload v12: the command channel can no longer be wedged.** `Run()` read the
  command's output through a pipe (`ReadToEnd()`) and only checked the 15 s timeout
  afterwards, so a grandchild that outlived the timeout kept the pipe open and
  blocked the single-threaded server forever — measured: one `grep -r /opt` made the
  channel deaf until a power-cycle. Output now goes to a temp file and the timeout
  kills the whole process tree; a runaway command returns
  `[timeout: killed after 15s]` and the channel keeps serving (verified with
  `sleep 40`).
- **Payload v13: auto-update is pinned off at every boot.** The TV's own update
  machinery (`swu-auto-upgrade.path` → `org.tizen.tv.swu.otascheduler`) would
  replace the app the payload lives in. The payload now re-asserts
  `db/menu/support/softwareupdate/autoupdate = 0` (system and user layers) via
  `buxton2ctl` and beacons the readback. The value was already 0, so this is
  enforcement rather than a change of state; verified after a reboot
  (`DSHROOT autoupdate … = Int32: 0`). Payload: 21,504 B, md5
  `176914345bcc81ca8c87de712b4a044f`.
- **Payload v11: a slow boot is now half as slow.** A boot whose task list is
  unreadable used to spend 20 s per failed round waiting for a landmark it could
  never see, plus 14 s scanning a landmark that reads back stale — 65 s before the
  channel appeared. Both budgets now give up early in fast mode (3 s landmark wait,
  5 scans) and let AUL relaunch a fresh process instead; the long fallback keeps the
  patient values. Measured on the same class of bad boot: **34 s instead of 65 s**
  (rounds fail in ~4 s, three attempts were needed). Payload: 20,480 B, md5
  `b0831d7abbfb25eab17f06186b29f41c`.
- **The blank exploit page had two causes, both on the PC.** First, the server was a
  console program under a job or Task Scheduler: when that console went away Windows
  terminated it with no traceback, and the page lost its endpoints a few seconds after
  loading. `safe_accept()` now wraps every `accept()` so a transient error cannot end
  the process, and the launcher keeps stderr in `logs/server.task.err`.
- **The page could run a stale builder.** `lib/wasm_builder.js?v=5` was a static cache
  key, so the TV could execute an old builder against a current payload and die before
  logging anything. Both scripts are now cache-busted, service workers are
  unregistered, and a `RUNNING_AT` marker separates "crashed inside the exploit" from
  "never started".
- **`RSET` raced the page.** The client helper resent `RSET` on every failed attach, so
  a stub that connected between two attempts was destroyed instantly, and the server
  also evicted clients that were merely waiting. Both sides fixed: the client does not
  reset while waiting, and the server only evicts a client that is actually paired.
- **`uninstall.sh` looked successful after a no-op delete.** It now reads the table
  back and aborts if the row survived.
- **The payload's SMACK label regression (the boot-persistence bug).** The DLL written
  by the browser stub carried the *browser's* label, so the app was denied read on its
  own assembly and died before `Main`. The fix — `chsmack` the app's `::RO` label after
  every copy, with a verified readback — is in both deploy and uninstall.
- **Payload v9: 11 minutes to root became ~40 seconds.** The first launch after a cold
  boot cannot read the task list reliably; v9 gives up quickly and lets AUL relaunch a
  fresh process instead of sleeping in the failed one.
- **Payload v6: warm-restart failures.** It snapshots existing `PHYRFORK` landmarks,
  waits for a *new* one, validates the cred before patching, and excludes stale
  orphans (`kill -9` of the app now re-roots in 8–11 s).
- **Payload v5: `fork()` copies the credential.** Patching a child's cred never roots
  the parent; the parent must be found through the child's `real_parent`. Also
  `Kptr()` had to accept addresses above `0xE0000000` — this LPAE kernel allocates
  tasks and creds there.
- **`deploy.sh` printed `COPY=ok` while every `cp` failed**; it now checks and aborts.
- **`readmany` desynchronised the stub** whenever a batch hit an unmappable page: the
  stub aborted the batch while the client kept reading, so every later read returned
  garbage and a scan looked like a clean negative. The client now stops at the bad page
  and restarts after it.

### Removed

- **Date/time stamps from the prose** (kept: a quoted TV log line, two external lab
  filenames, and a `schtasks /ST` argument).
- **The dated filename** `docs/BOOT-REGRESSION-SMACK-2026-10-22.md` → `BOOT-REGRESSION-SMACK.md`.

### Discovered (recorded in `docs/FAILED.md` so nobody repeats them)

- The **userspace relabel works**: a root shell can take the app's label with
  `echo -n "User::Pkg::<appid>" > /proc/self/attr/current`. That single fact replaced
  the kernel-memory relabel entirely and was what restored the payload.
- **Kernel-memory relabelling is impossible on this unit**: the `smack_known` struct
  lives above `0xE0000000` (vmalloc), so `phys = va - 0xA0000000` does not apply and
  the physmap cannot read it. 635 copies of the label string exist in the direct map
  and none is pointed at.
- **The app's process `comm` is `DN_trol-Service`**, not `MultiControl*` — every
  physical scan for the app was searching for a name that never exists.
- **The app is invisible in the browser shell's PID namespace**, so `/proc` looks empty
  while `aulctl status` reports it running.
- **`aulctl reload` does not restart a running app**; only stop+start does.
- The app lane is write-protected by label, not by permissions: the shipped SMACK
  policy grants no `User::Pkg::*` access to `User::Home`, so only the app's own label
  can write its files.

---

## 2026-10-21

### Added

- **Permanent-root design**: an on-boot service app on the writable `/opt` partition,
  running the V4L2 physmap chain at every boot. Confirmed live: `owner` is in group
  `video`, and 16 apps carry `app_onboot='true'`.
- **Boot-hook map** and a firmware-derived understanding of the boot chain: `systemd` is
  PID 1, `rc.sysinit` never runs, and the only exploitable boot hook is the app lane.

### Discovered (all negative, all recorded)

- **UEP blocks unsigned execution** on the shipped kernel, including tmpfs and memfd
  tricks that the GPL source suggests should work.
- **`sdbd root:on` is a dead end**: it compares a cached capability string that the
  shipped plugin never fills.
- **systemd does not read `/opt` units or drop-ins**, and D-Bus `StartTransientUnit`
  from uid 5001 is denied.
- The installer's absolute-path extraction creates **new files only**; it cannot
  overwrite the app's DLL.

---

## 2026-10-20

### Added

- **Browser code execution on the TV** (uid 5001) through CVE-2024-2887 (WasmGC type
  confusion) in Chromium 120, with the six firmware-specific ROP constants measured
  rather than copied.
- **Root** through the V4L2 physmap: `/dev/video40` passes an attacker-chosen
  `vm_pgoff` to `remap_pfn_range()`, giving arbitrary physical read/write from an
  unprivileged process in group `video`. Kernel Image at phys `0x20008000`,
  `init_task` at `0xC0957180`.
- **Firmware decryption and extraction** (MSD 1.1 key, VDFS4 partitions), which is what
  made the kernel layout, SMACK policy and boot chain knowable at all.

### Discovered

- The sdb route is dead on this firmware: the shell is whitelist-only and the
  published injection does not execute. The browser route needs no sdb and is the one
  that worked.
- The GPU CVEs in scope for the reported DDK version cannot apply: the GPU is a
  Mali-G51 Job-Manager part, and the vulnerable code paths are CSF-only.
