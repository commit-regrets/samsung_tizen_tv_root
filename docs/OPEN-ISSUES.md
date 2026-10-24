# Open issues — triaged from the code review

The review notes (`docs/REVIEW-FINDINGS-2026-10-23.md` and
`docs/REVIEW-FINDINGS-DUMMY-SECOND-PASS.md`, both untracked and marked "do not
commit") **were deleted on 2026-10-24** once every item below was closed. Their
detail and line numbers live on in this file, in `CHANGELOG.md`, and in the code
comments. This file is the record: what was broken, what fixed it, and how it was
proven.

State when this list was written: TV rooted with payload **v13** (21,504 B, md5
`176914345bcc81ca8c87de712b4a044f`), 47 tracked files, working tree clean.

Already fixed and committed with this handoff: **#9** (`patch_full` read `uid`
from `cred+40`, i.e. `cap_inheritable`; now `cred+4`, named cap offsets, proven by
`tools/sim_rpc.py`), prod `server/index.html` (it was the pre-fix copy: no service
worker unregister, static `?v=5` cache key), `payload/out1*` untracked, and the
stale doc constants (`v7` → v13, 36 → 47 files, sizes/hashes).

## Status 2026-10-24 — all PC-side items closed

Payload **v14** (23,040 B, md5 `5b798012ae35c9c567fa7a5ea91d6683`) is deployed and
verified on the TV, including a forced cold reboot.

| # | State | Evidence |
|---|---|---|
| 1 | **closed** | `Beacon()` 500 ms connect cap; boot after the change still rooted (`ROOTCHAN` +2 s after the successful attempt) |
| 2 | **closed** | fork children `close(_fd)` + `waitpid(WNOHANG)`; a boot-time attempt-1 failure followed by attempt-2 success no longer hits the 120 s open retry |
| 3 | **closed, proven on a stock state** | the stock IL/AOT were put back on disk and the backups deleted; the next deploy created them (`BACKUP_IL=ok`, `BACKUP_NI=ok`) with md5s `f61f60dd…` / `6c9bdcc4…` and recorded `mcs_orig.md5` / `mcs_ni_orig.md5` |
| 4 | **closed** | both `.ps1` pass `$TvIp`, check the exit code; `root_shell.py` also accepts `ROOT_TV` and fails on a broken stream. `uninstall.ps1 -NoWait` ran end-to-end on the TV: stock IL/AOT restored + relabelled, boot row removed (`remain=0`), `UNINSTALL_DONE`, exit 0 |
| 5 | **closed, proven on the TV** | `recover.sh` ran from the root channel: `RECOVER=deploy_local.sh` → deploy → `DEPLOY_DONE` → `RECOVER_DONE` |
| 6 | **closed** | lock released before `rpc_queue.get`; `tools/test_gateway.py` asserts `RSET` in ~2 ms while a client waits |
| 7 | **closed on hardware** | silent client dropped at 30 s, second client served in 31.3 s after it |
| 8 | **closed** | label verified on the temp DLL before the rename; boot-row and AUL failures now `exit 1`. `tools/test_shell.py` now exercises the label-mismatch and bad-boot-row aborts offline (a real mismatch on the TV is not forceable without breaking it) |
| 9 | **closed** | `POST /save` body cap 1 MB → 413, proven by the gateway test |
| 10 | **closed on hardware** | stub clamps `READ`/`WRITE32`/`READMANY`/`RUN`/`FILE`; live: oversized READ and cross-page WRITE refused with `-22` while the stub kept serving, overlong op 7 refused and ended the stub. Blob rebuilt (7552 B) and re-embedded automatically |
| 12 | **closed** | allowlist fails closed; `ALLOW=` printed before `COPY=ok` on the live deploy |
| 13 | **closed** | `SaneCred` (range, alignment, usage, ids) before every cred write; payload v14 |
| 14 | **closed** | shared `iter_owner_creds` with a 31-byte carry; `sim_rpc` self-test proves the straddle case |

P2 items are fixed as well (dead `physmap` modes removed, `MapPage` munmap,
`TrySelfUpdate` PE check + rollback, `tv_rootwatch` python discovery + loop, the
`physrpc.S`/blob drift, `find_task.py` runs from a clone, doc constants).

**Still open: nothing.** The review list is fully closed, and so is the last item
that sat outside it (`AGENTS.md` §11: 31337 binding). The offline layers are
`python tools/test_all.py`, the on-TV layer is `--tv` (`docs/TESTING.md`).

## Second-pass review — 2026-10-24 (later)

An independent re-read of the landed fixes found four leftovers. Three were
PC-only and are fixed; the fourth is a payload change, staged.

| # | Leftover | State |
|---|---|---|
| L1 | `tv_rootwatch.root_by_tail` returned `"already"` on the first uid-0 tag — a stale task's cred pointer can land on init's (or a previously patched) cred and hide the live uid-5001 stub | **fixed**: only uid-5001 creds are written, uid-0 tags are remembered without stopping; `already` only when no uid-5001 cred exists. Cases added to `tools/sim_rpc.py` |
| L2 | `deploy.sh` continued past `BACKUP_IL=fail` / `BACKUP_NI=fail`, so a failed stock snapshot still reached `COPY=ok`/`DEPLOY_DONE` and re-opened the no-backup hole | **fixed**: both `exit 1` before anything is replaced; four new `tools/test_shell.py` checks (IL and NI failure) with a `cp` stub that fails on demand |
| L3 | `SaneCred` accepts uid 0, and the payload patched a cred whose uid is 0 *or* 5001, so a bogus `real_parent` on init's cred would still be written | **fixed in payload v15**: `PatchCred` refuses anything but uid 5001 (uid 0 = already done); deployed and boot-verified 2026-10-24 21:38 |
| L4 | `tools/_selfroot.py` still used the single-hit walk; the two `REVIEW-FINDINGS-*.md` files are still on disk | `_selfroot.py` **fixed**; the review notes were **deleted** once L1–L3 were closed (untracked, so the content lives on in this file and `CHANGELOG.md`) |

**Do not repeat this session's mistakes:** the `:80` server MUST run as
`pysrv.exe` — Windows firewall has inbound *Block* rules for `python.exe`, so a
`python server.py` server is invisible to the TV (no page, no beacons) while it
looks fine from the PC's own loopback. The remote power button is standby, not a
boot; only a cold boot runs the AUL hook. **Do not reboot the TV with
`systemctl --force reboot` from the payload:** on 2026-10-24 that left the set in a
deep standby that the remote could not wake and only a mains unplug cleared. Ask
for a power cycle instead.

A second footgun found the same day: `kernel_root._find_tag_near_tail()` returned
only the *first* `PHYSRPC1` task, which can be a freed one from an earlier page
load, so `root_via_fork` retried six times on a dead cred pointer
(`skip 0xe234cf00 (not a cred)`) while the live stub sat further along. It now
collects every tagged task (`_find_tags_near_tail`) and patches whichever
validates; the same fix is in `tv_rootwatch.root_by_tail`.

## Environment — read before touching the TV

- **Work in this repo.** The `samsungtv` tree is reference material (vendored
  clones, firmware extract, the DWARF/kernel build). Nothing under it is needed to
  fix the items below, and nothing there should be edited as "the toolkit".
- **TV:** `192.168.178.175`, rooted, payload v14, channel on `31337`
  (`python tools/root_shell.py "id" 192.168.178.175`). PC: `192.168.178.214`.
- **Port 80 is the firewall's fault line.** The Windows firewall has inbound
  *Block* rules for `python.exe` and *Allow* rules for `pysrv.exe` (path
  `...\pythoncore-3.14-64\pysrv.exe`, plus a "TV lab HTTP (pysrv)" rule). Serve
  `server.py` with `pysrv.exe` or the TV cannot fetch the page and beacons never
  arrive. `root.ps1`'s `Find-Python` already prefers `pysrv.exe`; a manual
  `python server.py` does not.
- **Payload builds:** any dotnet SDK ≥ 8 builds the `net6.0` project; the
  `NETSDK1138` "out of support" warning is expected. A payload change means: rebuild,
  update `WANT=`/size in `server/deploy.sh`, deploy over the channel, reboot, and
  check the beacon chain — `AGENTS.md` §7/§9.
- **Do not launch a second server** while the task's one owns `:80`; the TV would
  fetch whichever answered.

## P0 — a promise the docs make that the code does not keep

| # | Issue | Why it matters | Fix sketch | How to verify |
|---|---|---|---|---|
| 1 | **`Beacon()` blocks with no connect timeout** (F15) | The headline claim is "root at boot with no PC". Every beacon is a synchronous `TcpClient.Connect`; a stale host on another subnet costs TCP SYN retries inside the ~40 s budget. The 38–47 s measurements were all taken with the PC reachable. | Short connect timeout (~500 ms) or fire-and-forget; keep the local marker file as the durable record. | Boot with the server **down**; measure first beacon → `ROOTCHAN`. Should stay ≈ the same. |
| 2 | **Fork children hold `/dev/video40` for 120 s** (F8, M1) | Each failed fast round forks a child that sleeps 120 s holding the inherited device fd, so the parent's `close()` frees nothing. The next AUL launch then sits in the 120 s `open()` retry — this is a plausible cause of the slow boots v11 tried to fix. | In the child: `close(_fd)` before the sleep (raw syscall only — `AGENTS.md` §9), and close before `Environment.Exit`. Reap children (`SIGCHLD`→`SIG_IGN` or `waitpid`). Payload rebuild: bump version, update `WANT=`/size, deploy, reboot. | Cold boot whose task list is unreadable; beacons must not show `fail open video40 after 120s`, and boot-to-root should tighten. |
| 3 | **Nothing creates `mcs_orig.dll` / `mcs_ni_orig.dll`** (F5) | `uninstall.sh` hard-fails without them. On this TV they exist because they were made by hand; a first-time user can root and then never cleanly uninstall. | In `deploy.sh`, before replacing anything, snapshot the current IL and `.native_image/*.ni.dll` to `share/mcs_orig.dll` / `mcs_ni_orig.dll` **if absent**, md5-gated the way `uninstall.sh` checks them. | On a stock TV: deploy, then compare both backups' md5 against the known stock values; then uninstall. |
| 4 | **`root_shell.py` address requirement breaks both `.ps1` callers** (F1) | `root_shell.py` exits 2 without an address (`$TV_IP` or argv[2]); `uninstall.ps1` and `root.ps1` call it with only the command, and `root.ps1` never checks `$LASTEXITCODE`, so it prints "Permanent root is up" even though the check never ran. The uninstall path cannot run at all. | Pass `$TvIp` as the second argument in both scripts and check the exit code. Audit other call sites and docs using the bare form. | `python tools/root_shell.py id` → exit 2 (confirms); after the fix, `root.ps1 -DryRun` and a real uninstall run. |
| 5 | **`recover.sh` fetches the un-rewritten `deploy.sh`** (F3) | `deploy.sh` still contains `H="http://HOST_IP"`; only `root.ps1` rewrites it (into `deploy_local.sh`). So `recover.sh` ends in `CURL_FAIL` and still prints `RECOVER_DONE`. It also points at `tools/chan.py`, which does not exist. | Fetch `deploy_local.sh` when present, else rewrite `H=` inside `recover.sh`; abort unless the output contains `DEPLOY_DONE`; fix the hint to `root_shell.py`. | Run `recover.sh` from a root shell on the current TV: expect `COPY=ok` … `DEPLOY_DONE`. |

## P1 — robustness; no user-visible promise broken

| # | Issue | Fix sketch |
|---|---|---|
| 6 | **Gateway holds `rpc_lock` while waiting** (F2) — `rpc_queue.get(1800)` runs inside the lock, so whenever a client is waiting (the common flow: the tool connects before the page is opened) `RSET`, forwarding and a second client all block. This is why `reset_stub()` can time out. | Claim the client slot under the lock, release it, wait on the queue, re-acquire to pair. Add the integration test below. |
| 7 | **31337 serves one client at a time with blocking reads** (F7) — one silent connection (port scan, half-open socket) makes the channel deaf until the app restarts. Same class as the v12 pipe wedge, one layer up. | Read timeout + maximum command length in `Serve()`. |
| 8 | **Fatal conditions report success** (F4) — `DLL_LABEL_MISMATCH`, `BOOT_ROW_WARN`, `AUL_RELOAD=fail`, and uninstall's `LABEL_WARN` are warnings, then `DEPLOY_DONE` / `UNINSTALL_DONE`. `auto_root.py` only requires `DEPLOY_DONE,COPY=ok`. | Make them `exit 1`. First check a live `DLL_LABEL=` line: if Tizen's `ls -lZ` ever prints extra fields, a correct deploy would start failing. |
| 9 | **`POST /save` Content-Length uncapped** (M2) — headers are capped, the body is not, so any LAN client can grow `logs/tv/`. | Cap the body (e.g. 1 MB) and reject the rest. |
| 10 | **No size enforcement between PC tools and the stub** (F11, M3) — `run_root`/`auto_root`/`write_root` send arbitrary lengths into fixed stub buffers (`cmdbuf 512`, `pathbuf 256`, `databuf 4096`); the stub never clamps `offset+len` to the mapped page. | Enforce 509 B commands, 255 B paths, 4096 B chunks client-side; clamp in the stub too. |
| 12 | **31337 allowlist fails open** (F12) — missing file ⇒ allow all, and `deploy.sh` writes the allow file *after* the DLL, so an interrupted deploy leaves an open root shell. | Write the allow file before the DLL; fail closed. Note the trade-off for hand-copied payloads in the docs. |
| 13 | **`PatchCred` has no sanity check** (M4) — it accepts any kernel-looking pointer whose cred uid is 0 or 5001, so a bogus `real_parent` could patch a foreign cred (even `init`). Python's `_sane_cred` is stricter. | Mirror `_sane_cred` in the payload (usage 1..0x10000, ids plausible) before writing. |
| 14 | **Cred scan misses a page-straddling pattern** (M5) — `scan_cred.py` and `tv_rootwatch` search each 4 K page with no overlap. Proven by the `sim_rpc.py` self-test: a 16/16 split is invisible per page, visible with 31 bytes of overlap. | Carry `PAT[:-1]` as overlap between pages. Extend the sim test to cover the fix. |

## P2 — hygiene, latent paths, or cosmetic

- **`physmap.py` dead modes** (F6): `full_root` calls `load_image_head()` (no uImage ships), then undefined `find_tasks_offset`/`walk_tasks`, and gates creds to `< 0xD0000000` while claiming success. Not on the production path (`kernel_root.py --fork`). Delete or repair.
- **`TrySelfUpdate()`** (F13): any `share/next.dll` over 1 KB replaces the payload with no hash check and no rollback. Add a pinned hash (or PE sanity) and keep the previous DLL.
- **`MapPage`** (F14): `Pages.Clear()` leaks mappings without `munmap`; the `mmap2` fallback's `r < 0` is too strict for a high-half mapping (a successful map is a negative `int32`). **Do not** touch `mmap64`'s `== -1` check — that half of the finding was wrong.
- **`tv_rootwatch.py`** (F16): hardcodes the author's `pysrv.exe`; loop mode returns after the first successful shell (only `--no-shell` loops).
- **Embedded shellcode ≠ `tools/physrpc.S`** (F10): the shipped blob's device path decodes as `/dev/video30`, the source says `/dev/video40`. It works (same driver family), but a rebuild + re-embed would silently switch nodes. Align them, or rebuild and re-verify, and add a build check comparing blob against assembly.
- **`root.ps1` may claim persistence it did not observe** (low): `deploy.sh` restarts the app in the background, so 31337 usually opens *before* any reboot. Wait for down-then-up, or say so plainly.
- **`uninstall.ps1`**: undeclared `$NoServer` (its `-NoServer` switch cannot bind); `Stop-ToolkitServer` lacks the process-name check that `root.ps1` has; it waits only 20 s for 31337 to reappear while payload startup measures ~40 s — a false "uninstall verified" is possible.
- **`server.py` shell bookkeeping**: `tv_sock` is never cleared on disconnect, the global `output` grows unbounded, and `control_client`'s saved offset can exceed `len(output)` after a clear (swallowing that client's output).
- **Doc/naming hygiene**: `root_shell.py`'s docstring says `chan.py` (it is the `chan.py` client renamed); `_selfroot.py` and `taskwalk.py` are diagnostics with sharp edges — label them as such.
- **Delete the two `REVIEW-FINDINGS-*.md` files** once the list above is closed.

## Tests to add (they would have caught these)

1. **Fake-RPC unit tests** — `tools/sim_rpc.py` is now in the repo (`python tools/sim_rpc.py` self-test). Extend it: page-straddle scan (M5) and the `PatchCred` sanity analogue.
2. **Gateway integration test** — start `server.py` on a scratch `HTTP_PORT`, attach a waiting client on 9998, assert `RSET` answers within ~1 s, then queue a fake `PGDB` stub and assert pairing/forwarding. Catches #6.
3. **Shell dry tests** — run `deploy.sh`/`uninstall.sh` under `sh` with stubbed `curl`/`sqlite3`/`chsmack`/`aulctl` on `PATH`; assert non-zero exit on label/boot-row mismatch (#8) and that the stock backups get created (#3).
4. **PowerShell** — `root.ps1 -DryRun` and `uninstall.ps1 -DryRun` after #4, plus a stubbed `root_shell.py` invocation test.

## Suggested order

1. #4 (one line ×2) — restores the uninstall path.
2. #6 — gateway lock restructure.
3. #8 + #3 — fail loud, and create the backups.
4. #5 — recover path.
5. #2 + #1 + #7 — payload: close the device in children, beacon timeout, channel read timeout. Payload rebuild, `WANT=`/size, deploy, reboot, verify per `AGENTS.md` §7.
6. #14, #13, #10, #12 — sanity, sizes, allowlist ordering.
7. #9, then P2.

Payload work is the only part that needs a TV round-trip and a reboot; do the PC-side
items first so a reboot validates several changes at once.
