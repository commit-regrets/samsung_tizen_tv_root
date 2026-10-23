# Open issues — triaged from the code review

The review itself is `docs/REVIEW-FINDINGS-2026-10-23.md` plus
`docs/REVIEW-FINDINGS-DUMMY-SECOND-PASS.md`. **Both are untracked working notes**
(the reviewer marked them "do not commit"): they hold the detail and the line
numbers. This file is the work list — what to fix, in what order, and how to
prove each fix. Close items here as you go, add a `CHANGELOG.md` entry per fix
(`AGENTS.md` §0), and delete the two review files when the list is done.

State when this list was written: TV rooted with payload **v13** (21,504 B, md5
`176914345bcc81ca8c87de712b4a044f`), 47 tracked files, working tree clean.

Already fixed and committed with this handoff: **#9** (`patch_full` read `uid`
from `cred+40`, i.e. `cap_inheritable`; now `cred+4`, named cap offsets, proven by
`tools/sim_rpc.py`), prod `server/index.html` (it was the pre-fix copy: no service
worker unregister, static `?v=5` cache key), `payload/out1*` untracked, and the
stale doc constants (`v7` → v13, 36 → 47 files, sizes/hashes).

## Environment — read before touching the TV

- **Work in this repo.** The `samsungtv` tree is reference material (vendored
  clones, firmware extract, the DWARF/kernel build). Nothing under it is needed to
  fix the items below, and nothing there should be edited as "the toolkit".
- **TV:** `192.168.178.175`, rooted, payload v13, channel on `31337`
  (`python tools/root_shell.py "id" 192.168.178.175`). PC: `192.168.178.214`.
- **The :80 server is a scheduled task (`TV-LabServer`) that currently serves the
  LAB copy** (`samsungtv\lab_server\server.py`), not this repo. That is a drift
  risk: a payload or script change made here is not what the TV fetches until the
  copies are synced. Either
  (a) stop the task and let `root.ps1` own `:80` for the test, or
  (b) repoint the task at this repo's `server\run_server.vbs`, remembering that
  `run_server.cmd` picks its interpreter from `TV_PY` (default `python`) and the
  Windows firewall rule is pinned to one program path — on this PC
  `...\pythoncore-3.14-64\pysrv.exe`.
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
