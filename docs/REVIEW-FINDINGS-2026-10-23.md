# Code review findings — 2026-10-23 (TEMPORARY HANDOFF)

> **This file is a temporary, uncommitted review handoff. Do not commit it.**
> Work through the findings, then **delete this file**. Fixes themselves are
> normal changes: each one gets an entry in `CHANGELOG.md` (see `AGENTS.md` §0)
> and must respect the traps in `AGENTS.md` §8 and the payload invariants in
> `AGENTS.md` §9. Line numbers below were accurate at commit `c30a2f4`
> (payload v13); re-check before editing.

## Scope and method

- Reviewed: the 63 tracked files in this repo — `payload/Program.cs`,
  `server/server.py`, `server/*.sh`, `server/index.html`,
  `server/payloads/browser_payload.js`, `tools/*.py`, `tools/physrpc.S`,
  `root.ps1`, `uninstall.ps1`.
- The repos under `C:\Users\Raghav\Documents\projects\samsungtv\` are
  third-party / reference material and were **not** reviewed; they were only
  spot-checked for provenance of the embedded shellcode.
  `server/lib/wasm_builder.js` is the upstream V8 test harness.
- No TV was attached: static review plus PC-side live tests (below).
- Verified good, do not re-litigate: all `tools/*.py` + `server/server.py`
  compile; `server/payload.dll` md5 `176914345bcc81ca8c87de712b4a044f` matches
  the `deploy.sh` gate and `payload/out13/`; the v13 payload core (cred
  validation before patching, patch the parent not the fork child, full
  `0xC0000000..0xFFFFFFFF` `Kptr`) is correct; `patchCallbackBytes` in the
  browser payload matches exactly one sockaddr in the shellcode.
- The repo currently has **no automated tests**. Several findings below would
  have been caught by two small ones (see "Suggested tests").

## Second-pass audit (same day, do not skip)

An independent re-read of the code against every finding. Verdicts:

| # | Verdict | Note |
|---|---|---|
| 1 | **Correct, slightly understated** | Env names also diverge: `.ps1` uses `ROOT_TV`, `root_shell.py` uses `TV_IP`. Setting `ROOT_TV` (as the scripts document) does **not** satisfy Python. |
| 2 | **Correct** | Reproduced; `queue.get(1800)` is inside `rpc_lock`. |
| 3 | **Correct** | `recover.sh`'s `$H` is only used to *fetch* `deploy.sh`; the fetched script still has `H="http://HOST_IP"`. After uninstall, `rootchan.host` is gone, so the user must pass the PC IP — and it still would not rewrite deploy's download URL. |
| 4 | **Correct as a bug; fix needs care** | Non-fatal is real. Making `DLL_LABEL_MISMATCH` a hard `exit 1` is right **if** `ls -lZ` + awk returns exactly `User::Pkg::…::RO`. If Tizen prints the label with extra fields, a working deploy would start failing. Check a live `DLL_LABEL=` line before flipping to fatal. |
| 5 | **Correct** | No script writes `mcs_orig.dll` / `mcs_ni_orig.dll`. Docs treat them as already on the TV. |
| 6 | **Correct but over-ranked** | Dead `full_root` / missing `uImage` / `NameError` / truncated `0xD0000000` bound are all real. **Not on the production path** (`kernel_root.py --fork`). Demote to medium. |
| 7 | **Correct** | Sequential accept + blocking `Read` with no timeout. |
| 8 | **Correct, and incomplete — see M1** | Child never closes `_fd`; ARM stub does. |
| 9 | **Correct; fixed** | `cred+40` is `cap_inheritable`; uid is `cred+4`. `patch_full` now reads +4. |
| 10 | **Correct as a rebuild footgun, not a live bug** | Decoded blob path at offset `0x5ba` is `/dev/video30` (sits where `physrpc.S` puts `path:`). The running page uses that blob; `physrpc.S` is not what is embedded. |
| 11 | **Correct** | Stub `recv_full` trusts the header length. |
| 12 | **Correct, with a documented trade-off** | Fail-open on missing file is commented `legacy: open to all`. Fail-closed would break a hand-copied payload with no allow file. Still write the allow file *before* the DLL. |
| 13 | **Correct, unused path** | `AGENTS.md` §11 already calls `next.dll` unused. Latent, not live. |
| 14 | **Half-wrong** | `Pages.Clear()` leak is real. The mmap *error* claim is inverted: `mmap64` checking `== -1` is the correct libc convention. The `mmap2` fallback `if (r < 0)` is **too strict**, not too loose — a successful mapping in the top half of VA (research log: `0xafa4c000`) is a negative `int32` and would be thrown away. Production currently hits `mmap64` first (it works, or boot-to-root would fail). Do not "fix" mmap64 to treat `-4095..-1` as mmap() errors. |
| 15 | **Correct, possibly more important than ranked** | Boot-to-root is documented as working with no PC, but every `Beacon()` is a blocking `TcpClient.Connect` with no timeout. If the PC is off, SYN retries can stretch the ~40 s budget. Measured 38–47 s boots were likely with the PC reachable (beacons were being logged). |
| 16 | **Correct** | Hardcoded `pysrv.exe` path; default loop+shell returns 0 after the first `op 5`. |

Low/hygiene items all checked: `$NoServer` is undeclared; `find_task.py` really imports missing `smack_borrow`; `AGENTS.md` §6 still quotes 17,920 B / `d247e67a…`; `wasm_builder.js?v=5` is still a static cache key.

### Missed (add these)

**M1. Fast-exit leaves landmark children holding `/dev/video40` (high, related to 8).**
`Environment.Exit(0)` at `Program.cs:668` does not kill `fork()` children. Each failed fast round already forked a child that sleeps 120 s with the inherited device fd. The next AUL launch then spends up to 120 s in the `open("/dev/video40")` retry loop — which is exactly what v9 fast-mode was meant to avoid. Close `_fd` in the child **and** before `Exit`; do not treat finding 8 as "only after SUCCESS".

**M2. POST `/save` `Content-Length` is uncapped (medium).**
`server.py:_read_full_request` caps the *header* at 1 MB, then reads `clen` bytes with no maximum. Anyone on the LAN can grow `logs/tv/` without bound. Cap `clen` (e.g. 1 MB) and reject the rest.

**M3. Stub `op_read` / `op_write` do not clamp `offset+len` to the mapped page (medium).**
`physrpc.S` `add r1, r9, r10` then `send_full`/`str` with `r11` as length/value. `physmap.py` happens to chunk within 4 K; a bad client (or finding 11 overflow) reads/writes past the `mmap`ed page. Clamp in the stub.

**M4. C# `PatchCred` will patch *any* cred whose uid is 0 or 5001 (medium).**
No refcount / `_sane_cred` analogue. A bogus `real_parent` that still looks like a kernel pointer and whose cred is uid 0 would patch that cred (possibly `init`). Python `root_via_fork` is stricter. Mirror `_sane_cred` in the payload.

**M5. `scan_cred.py` / `tv_rootwatch.root_by_cred_scan` miss a 32-byte pattern that straddles a page (low).**
`data.find(PAT)` is per 4 K page with no overlap window.

Cosmetic, not worth a ticket: `browser_payload.js` check labels say `mpLR@0x48` / `mpPC@0x4c` but the constants used are `L_MPLR=0x044` / `L_MPPC=0x048` — the comparison is correct, the log strings are not.

---


## Critical / high

### 1. `uninstall.ps1` can never run; `root.ps1` final verification silently fails
- `tools/root_shell.py:9-12` exits `2` unless given a TV address
  (`sys.argv[2]` or `$TV_IP`).
- `uninstall.ps1:225` and `root.ps1:302` both invoke it with only the command
  string — no `$TvIp`. `root.ps1` also never checks `$LASTEXITCODE`, so it
  prints "Permanent root is up" and exits 0 even when the check never ran.
- Reproduced: `python tools/root_shell.py id` without `TV_IP` → exit 2.
- **Fix:** pass `$TvIp` as second argument in both scripts; check
  `$LASTEXITCODE` in `root.ps1`. Audit other `root_shell.py` call sites /
  docs that use the bare `root_shell.py "id"` form.

### 2. Gateway holds `rpc_lock` while blocking up to 30 min — `RSET` defeated
- `server/server.py:282-290`: `rpc_gateway_client` calls
  `rpc_queue.get(timeout=1800)` **inside** `with rpc_lock:`.
- Reproduced live: started `server.py`, attached one waiting gateway client,
  sent `RSET` from a second socket → **no reply after 3 s**
  (`tools/physmap.py:reset_stub()` gives up at 5 s). While a client waits for
  a stub, `RSET`, `rpc_tv_reader` forwarding, and any second client all block.
  This is the common flow: `auto_root.py`/`root.ps1` connect *before* the page
  is opened.
- **Fix:** claim the client slot under the lock, release it, wait on the
  queue, re-acquire to pair. Add the integration test under "Suggested tests".

### 3. `recover.sh` fetches the un-rewritten `deploy.sh`, then reports success
- `server/recover.sh:49`: `curl -s "$H/deploy.sh" | sh`. The served
  `server/deploy.sh:5` still has `H="http://HOST_IP"` — only `root.ps1`
  rewrites it, into `deploy_local.sh`. So the payload download goes to
  `http://HOST_IP/payload.dll` → `CURL_FAIL`.
- No `set -e`/pipefail, so `recover.sh:50` prints `RECOVER_DONE` anyway.
- The verify hint at `recover.sh:51` names `tools/chan.py`, which does not
  exist (it is `tools/root_shell.py`).
- **Fix:** fetch `deploy_local.sh` when present or rewrite the `H=` line in
  `recover.sh`; abort unless the deploy output contains `DEPLOY_DONE`;
  fix the hint.

### 4. `deploy.sh`/`uninstall.sh` "verify" fatal conditions, then report success
- `server/deploy.sh:57`: `[ "$GOT_LABEL" = "$WANT_LABEL" ] || echo DLL_LABEL_MISMATCH`
  — warning only, script continues to `DEPLOY_DONE`. A label mismatch is the
  2026-10-22 boot regression (`docs/BOOT-REGRESSION-SMACK.md`): the app dies
  before `Main` at next boot.
- `server/deploy.sh:73`: same pattern for `BOOT_ROW_WARN` (no boot row = no
  persistence), and `AUL_RELOAD=fail` is likewise non-fatal.
- `tools/auto_root.py` only requires `DEPLOY_DONE,COPY=ok`, so `root.ps1`
  declares a verified deploy in all these cases.
- `server/uninstall.sh:22`: `LABEL_WARN` → still prints `UNINSTALL_DONE`,
  which `uninstall.ps1:227` trusts. (Contrast `uninstall.sh:85`, which
  correctly exits 1 on a surviving boot row.)
- **Fix:** make label mismatch, boot-row mismatch, and (in uninstall) label
  mismatch exit 1.

### 5. Nothing creates the stock backups uninstall depends on
- `server/uninstall.sh:34-40` hard-fails (`NO_IL_BACKUP`) without
  `share/mcs_orig.dll` (md5 `f61f60dd…`); the AOT restore expects
  `share/mcs_ni_orig.dll` (`6c9bdcc4…`).
- No script creates either. `server/deploy.sh:39` "backup" copies the
  *incoming* payload to `payload_backup.dll`, not the stock DLL being
  replaced. On the author's TV the backups exist because they were made by
  hand, outside the scripts; a first-time `root.ps1` run on a stock TV makes
  uninstall impossible.
- **Fix:** in `deploy.sh`, before replacing anything, snapshot the current
  `bin/MultiControlService.dll` and `.native_image/*.ni.dll` to
  `mcs_orig.dll`/`mcs_ni_orig.dll` when absent, md5-gated like uninstall.

### 6. `physmap.py` `verify`/`root`/`rootexec` modes are dead on a fresh clone
- `tools/physmap.py:453` (`full_root`) calls `load_image_head()`
  unconditionally → `FileNotFoundError`: the repo ships no
  `firmware/extracted/uImage` (reproduced). `main`'s `verify` at :526 too.
- `tools/physmap.py:489,495` call `find_tasks_offset(...)` / `walk_tasks(...)`
  — neither is defined anywhere → `NameError` once the above is fixed.
- `tools/physmap.py:510` patches only creds with
  `0xC0000000 <= c < 0xD0000000`, silently skipping creds above that
  (`AGENTS.md` trap #5) while keeping `ok = True`.
- The `kernel_root.py --fork` path is unaffected. **Fix:** delete `full_root`
  or repair all three; make `find_image_base`'s constant-signature fallback
  the only path when the uImage file is absent.

### 7. Root channel (31337) wedged by one silent connection
- `payload/Program.cs:333-355` `RootChannel()` serves one client to
  completion before accepting the next; `Serve()` at :359-385 does blocking
  `s.Read` with no timeout and accumulates an unbounded line buffer.
- One allowed-IP connection that sends nothing (scan, half-open socket)
  makes the channel deaf until the app restarts — same class as the v12
  `Run()` pipe wedge (`CHANGELOG.md`), one layer up.
- **Fix:** socket read timeout + max command-line length in `Serve()`.

### 8. Payload fork children hold `/dev/video40` for 120 s; never reaped
- `payload/Program.cs:523-528`: the `fork()` child only calls
  `syscall(172, 15, …)` (PR_SET_NAME), `usleep(120000000)`, `_exit(0)`.
  It never closes the inherited `_fd`.
- So the parent's `close(_fd)` at :652 does not free the device — the open
  file description survives until the last landmark child exits (up to
  120 s × rounds), which can block the browser physmap path (`AGENTS.md`
  trap #3). The ARM stub's `fork_child` (`tools/physrpc.S`) explicitly
  closes socket + device fd; the C# port missed it.
- Children are also never `waitpid()`'d → zombies for the life of
  `RootChannel()`.
- **Fix:** in the child, `close(_fd)` before the sleep (raw syscall only —
  keep the §9 rule: no managed allocations post-fork); reap children or set
  `SIGCHLD` to `SIG_IGN`. Rebuild payload, bump version, update
  `WANT=`/size in `server/deploy.sh`, follow `AGENTS.md` §9 invariants.

---

## Medium

### 9. `kernel_root.patch_full` verifies `cap_inheritable`, not uid
**Fixed** (uid readback is `cred+4`; confirm with `python tools/sim_rpc.py`). Original:
- `tools/kernel_root.py:176-179` reads `cred+40` and labels word 0 as uid.
  `struct cred` layout: ids at +4…, `securebits` +36, `cap_inheritable` +40,
  `cap_permitted` +48, `cap_effective` +56. The uid read-back must be at
  `cred+4`.
- Reproduced with a fake RPC (inheritable `0x11223344`, caps correct):
  prints `uid=287454020` and returns `False`.
- Passes in practice only because inheritable is usually 0. Affects
  `root_via_fork`, `scan_cred.py`, `tv_rootwatch.py` success reporting.
- **Fix:** read 76 bytes from `cred`, check ids at +4 and caps at +48/+56.

### 10. Embedded shellcode ≠ `tools/physrpc.S` (device node differs)
- Decoding `SHELLCODE` in `server/payloads/browser_payload.js` (7,440 B):
  path string is `/dev/video30`. `tools/physrpc.S:467` and the JS comment
  (line 83) say `/dev/video40`. Research notes
  (`samsungtv/recon/VIDEO-PHYSMAP-2026-10-20.md`) say video30/40/60 are the
  same driver family, so the live blob works — but a rebuild + re-embed
  would silently switch nodes, untested. `AGENTS.md` §11 already lists
  automating re-embedding as open work.
- **Fix:** either change `physrpc.S` to `/dev/video30` to match the proven
  blob, or rebuild/re-embed with video40 and re-verify on hardware; add a
  build check comparing the embedded blob against the assembled output.

### 11. PC tools do not enforce stub buffer sizes
- `tools/physrpc.S`: `cmdbuf .space 512`, `pathbuf .space 256`,
  `databuf .space 4096`; `recv_full` writes as many bytes as the header
  requests, into adjacent data.
- `tools/run_root.py`, `tools/auto_root.py` (op 7) and `tools/write_root.py`
  (op 8) send arbitrary command/path/chunk lengths with no checks.
- **Fix:** enforce command ≤ 509 B (512 − `"-c\0"`), path ≤ 255 B, chunk
  ≤ 4096 B client-side; ideally also clamp in the stub.

### 12. 31337 allowlist fails open
- `payload/Program.cs:317-330` `PeerAllowed()` returns `true` if
  `rootchan.allow` is missing **and** on any exception.
- `server/deploy.sh` writes the allow file only *after* copying the DLL
  (:40 vs :62), so an interrupted deploy leaves an unauthenticated root
  shell on `0.0.0.0:31337` at next boot.
- **Fix:** fail closed; write `rootchan.allow` before the DLL in deploy.

### 13. `TrySelfUpdate()` — unvalidated replacement, no rollback
- `payload/Program.cs:292-313`: any `share/next.dll` > 1 KB replaces the
  running payload via `File.Move(tmp, me, true)`; no md5/signature check,
  no backup of the current DLL. A corrupt drop bricks boot persistence.
- **Fix:** verify against a pinned hash (or at least MZ/PE sanity + length),
  keep the previous DLL for rollback, beacon the result.

### 14. `MapPage` leaks mappings; mmap error check incomplete
- `payload/Program.cs:106`: `Pages.Clear()` drops bookkeeping without
  `munmap` — up to 8,192 leaked pages per clear, duplicate re-maps.
- :100 checks only `p == IntPtr(-1)`; mmap failure returns `-errno` in
  `[-4095, -1]`, so other failures would be dereferenced as pointers.
- **Fix:** evict + `munmap` (libc syscall 91), or size the cache to the
  real working set; treat `(long)p >= -4095 && (long)p < 0` as failure.

### 15. `Beacon()` has no connect timeout on the boot path
- `payload/Program.cs:80-89`: synchronous `TcpClient.Connect` to
  `rootchan.host`/compiled default, called repeatedly before rooting.
  A stale host on a foreign subnet can cost TCP timeouts per beacon,
  against the ~40 s boot budget (`AGENTS.md` §1).
- **Fix:** short-timeout connect (or defer beacons until after rooting).

### 16. `tv_rootwatch.py` hardcodes the author's PC; loop mode exits early
- `tools/tv_rootwatch.py:51-53`: `PYSRV` defaults to
  `C:\Users\Raghav\AppData\Local\Python\pythoncore-3.14-64\pysrv.exe`;
  `ensure_server()` gives up if that exact file is missing instead of
  falling back to `python` on PATH — contradicts the v10 host-independent
  design. (`root.ps1`'s `Find-Python` is the model to copy.)
- In loop mode with shell enabled, a successful `send_shell()` returns 0
  immediately (~:203), so `--interval` only actually loops with `--no-shell`.

---

## Low / hygiene

- **`root.ps1` claims persistence it did not observe** (`root.ps1:285-302`):
  it waits for 31337 without gating on the reboot actually happening, but
  `deploy.sh` already restarted the app in the background, so 31337 normally
  opens *before* any reboot. Wait for the port to go down-then-up, or prompt.
- **`uninstall.ps1:204` uses undeclared `$NoServer`** (dead branch; passing
  `-NoServer` errors at binding). Its `Stop-ToolkitServer` lacks the
  process-name check present in `root.ps1` (`docs/SCRIPT-REVIEW.md` #3 fixed
  only one copy). Post-reboot it waits only 20 s for 31337 to reappear while
  measured payload startup is ~40 s — possible false "uninstall verified".
- **`tools/find_task.py` cannot run from this repo:** imports `smack_borrow`
  (:26), which exists only in the reference tree (reproduced
  `ModuleNotFoundError`); hardcodes `C:\Users\Raghav\…\tools` (:19);
  defaults `--comm MultiControl` although the discovered app comm is
  `DN_trol-Service` (`AGENTS.md`, `docs/FAILED.md`).
  `docs/SCRIPT-REVIEW.md:66-67` and `docs/PORTABILITY.md:77` claim
  `smack_borrow.py` / `dwarf_offsets.py` ship in `tools/` — neither does.
  Port `smack_borrow` in, or mark these tools reference-only and fix docs.
- **Stale constants in docs:** `AGENTS.md` §6 reproduce/verify steps quote
  17,920 B / `d247e67a…` (pre-v13) against §1 + `deploy.sh` (21,504 B /
  `17691434…`); `AGENTS.md` §5 says "Program.cs (v7)" and "36 files";
  `.gitignore` header says "18 KB artifact". Actual: 63 tracked files.
- **Tracked build snapshots:** `payload/out10`–`out13` (16 files, ~692 KB)
  are committed although `payload/out/`, `bin/`, `obj/` are ignored and
  `AGENTS.md` §5 describes only source + `server/payload.dll` as committed.
  Decide: keep one snapshot dir intentionally (and document it) or remove.
- **`server/server.py` shell-slot bookkeeping:** `tv_sock` never cleared on
  disconnect (`tv_reader`, :203-218); global `output` grows unbounded and
  `control_client`'s saved offset can exceed its length after
  `output.clear()` on a new shell, swallowing that client's output (:349+).
- **`server/index.html:34`** still loads `lib/wasm_builder.js?v=5` (static
  cache key) and contains no service-worker unregister, despite the
  changelog entry claiming both were fixed — only the payload script got
  `&t=Date.now()`. Bump/unify the cache-busting.
- `tools/root_shell.py:3` docstring and `server/recover.sh:51` still say
  `chan.py`. `tools/_selfroot.py`, `tools/taskwalk.py` are diagnostics with
  sharp edges (e.g. `taskwalk` treats any non-`next` direction as `prev`) —
  fine if labelled as such.

## Suggested tests (add with the fixes)

1. **Fake-RPC unit tests** for `kernel_root.patch_full` / `_sane_cred`
   (dict-backed `read`/`write32`): catches finding 9 and guards the cred
   layout constants.
2. **Gateway integration test**: start `server.py` on a scratch
   `HTTP_PORT`, attach a waiting client on 9998, assert `RSET` answers
   within ~1 s; then queue a fake `PGDB` stub and assert pairing/forwarding.
   Catches finding 2.
3. **Shell-script dry tests**: run `deploy.sh`/`uninstall.sh` under `sh`
   with stubbed `curl`/`sqlite3`/`chsmack`/`aulctl` on PATH; assert non-zero
   exit on label/boot-row mismatch (finding 4) and backup creation
   (finding 5). Note: no `sh` was available on the review PC — run in WSL
   or on the TV.
4. **PowerShell**: `root.ps1 -DryRun` / `uninstall.ps1 -DryRun` in CI after
   finding 1, plus a stubbed-`root_shell.py` invocation test.

## Suggested fix order

1. Finding 1 (one line ×2) — restores the uninstall path.
2. Finding 2 — gateway lock restructure.
3. Findings 4 + 5 — deploy fail-loud + stock backups.
4. Finding 3 — recover path.
5. Findings 8 + M1 + 7 — payload child fd close (including the fast-exit
   path); channel read timeout. (Payload rebuild: bump version, update
   `deploy.sh` `WANT=`/size, `CHANGELOG.md` entry, verify per `AGENTS.md` §7.)
6. Findings 6 + 9 — dead `physmap` path; `patch_full` offsets. Finding 6
   is medium, not production-path.
7. M2–M4, then the rest. Delete this file when done. Do **not** "fix"
   finding 14's mmap64 `-1` check (that part was wrong).
