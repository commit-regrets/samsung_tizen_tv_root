# Script review — production readiness

> **18:42 additions — server hosting/stability (see `docs/SERVER-HOSTING.md`).**
> `safe_accept()` now wraps every `accept()` (http, ctrl, rpc): a transient
> `OSError` there used to end the main thread and therefore the process, with the
> traceback going to a console nobody could see. `RSET` also drops a stale local
> client, so a cancelled client can no longer hold the gateway slot (`BUSY` for
> everyone after it). The server is now started by scheduled task `TV-LabServer`
> through `wscript` (a console app under Task Scheduler is silently terminated
> when its console closes — that was the "TV page goes blank" bug), with
> stdout/stderr in `server/logs/server.task.out|.err`.
> `index.html` cache-busts both JS files, unregisters service workers and posts
> `RUNNING_AT`; `lib/wasm_builder.js?v=5` was a *static* cache key, so the TV could
> run a stale builder against a current payload and die before logging anything.

Audit of the toolkit in this repo (2026-10-22). Scope: `root.ps1`,
`uninstall.ps1`, `server/server.py`, `server/deploy.sh`, `server/uninstall.sh`,
and `tools/*.py`.

## Fixed in this pass

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | **high** | `auto_root.py` returned success even when the deploy script failed — `run()`'s output was discarded, so `root.ps1` printed "Deploy verified" after a failed `cp`. | It now requires `DEPLOY_DONE` and `COPY=ok` in the output (`--expect`), and exits non-zero otherwise. |
| 2 | **high** | `root.ps1 -RestartServer` only restarted when the server was *not* ours. Reusing our own server kept stale RPC waiters, which stole the next stub (hit live twice). | `-RestartServer` now always stops and starts the server. |
| 3 | medium | `Stop-ToolkitServer` would kill any process whose command line contained `server.py`/`shellsrv.py`. | It now also requires the process name to be `python`/`pysrv`. |
| 4 | medium | A stale `/tmp/keep_boot` marker from an earlier run could silently keep the boot row during uninstall. | `uninstall.ps1` removes the marker unless `-KeepBoot`. |
| 5 | medium | `server.py` appended to `shell.log` without bound — it reached **58 MB** during this project. | Rotates to `shell.log.1` at 8 MB. |
| 6 | medium | The HTTP server would serve its own source and logs to anyone on the LAN (`/server.py`, `/shell.log`, `/server.out`). | Deny list: `.py .log .out .err .db .pem .key .journal` and the known log names → 404. |
| 7 | low | A slow HTTP client could block the single-threaded accept loop indefinitely. | 10 s socket timeout for HTTP handling. |
| 8 | low | `uninstall.sh` picked an arbitrary `.native_image.disabled.*` directory if several existed. | `ls -dt` (newest first). |
| 9 | low | No attribution/requirements files. | `NOTICE.md` (hdbreaker attribution) and `tools/requirements.txt` (keystone/capstone, rebuild only). |
| 10 | **high** | The boot payload latched onto a stale `PHYRFORK` orphan left by an earlier AUL restart, so it patched the wrong cred and failed on warm restarts (`self=0`, `fail no parent`, `fail no PHYRFORK`). `kernel_root.py`'s fork path had the same flaw. | v6 payload: snapshot existing `PHYRFORK` tasks before forking, scan up to 20 s for a **new** one, validate the cred uid before patching, keep the landmark alive for 120 s. `kernel_root.py` now excludes known orphans too. Tested twice: channel back in 11 s and 8 s. |
| 11 | medium | `deploy.sh` / `uninstall.sh` copied straight onto the live DLL; a kill mid-copy could leave a truncated file and the app unloadable. | Copy to `*.tmp` in the same directory, then `mv` (atomic rename). Verified with a live deploy: `COPY=ok`. |
| 12 | medium | `physmap.readmany()` desynchronised whenever the stub hit an unmappable page: `op_readmany` aborts the whole batch (`rm_err` → main loop), but the client kept expecting pages, so every later read returned garbage (looked like random kernel data). | The client now stops the batch at the bad page and restarts after it; verified `readmany` == direct read on the same page. |

## Race conditions — status

| Race | Status |
|---|---|
| Parent scans before the child sets its comm, then patches a stale `PHYRFORK` orphan | **Fixed** (v6 pre-fork snapshot + wait for a *new* child). Tested on two warm restarts. |
| `kernel_root.py` picks the first `PHYRFORK` for the same reason | **Fixed** with the same exclusion set, but only as reliable as the task list itself (below). |
| Half-written DLL if the app dies during `cp` | **Fixed** (temp + atomic rename). |
| Stale RPC waiter consuming the next stub | **Mitigated**, not structural: `-RestartServer` now always restarts; there is still no liveness check on the gateway. |
| Slow HTTP client blocking the accept loop | **Mitigated**: 10 s socket timeout; server is still single-threaded. |
| Task list corrupted while walking it (tasks exiting, fork churn) | **Open**. Both `prev` and `next` were observed broken on a warm system; retries and the orphan snapshot help but cannot repair the list. A pid-hash/IDR locator would fix it, but both routes are blocked (below); the remaining option is a physical comm scan. |
| `/dev/video40` opener conflict (browser vs app) | **Open** by design: one RDWR opener; v6 still exits if the browser holds it. Retry loop is open work. |

## Known limitations (accepted / documented)

- **RPC gateway has no liveness check.** A client that disconnects while waiting
  leaves a waiter that consumes the next stub. Mitigation: `root.ps1
  -RestartServer`, or start the server fresh before a run. A full fix needs a
  pairing protocol change.
- **Single-threaded HTTP accept loop.** Fine for one TV; a hostile LAN client
  could still slow the page load. The timeout limits the damage.
- **No authentication.** The RPC gateway binds `127.0.0.1` only; the TV root
  channel binds `0.0.0.0:31337` and is intentionally a LAN-wide root backdoor.
  Restrict it at the router or rebuild the payload with a bind address.
- **Hardcoded firmware constants** (`init_task`, offsets, Image base). Documented
  as per-firmware; re-measure on another model.
- **Hardcoded payload md5** in `deploy.sh` and `uninstall.sh`. Update both when
  the payload changes, or the deploy correctly refuses to install it.
- **Wedged TV stubs are now cleared with an `RSET` sentinel** on the RPC gateway
  (was: restart the server). `physmap.reset_stub()` returns `OK`/`IDLE`; the
  gateway drops the paired socket so the next page load pairs cleanly. Stubs are
  single-use for `op 7`, and `op 8` must never be sent to a stub already turned
  into a shell by `op 5`.
- **Log rotation keeps one generation** (`logs/shell.log` → `logs/shell.log.1`);
  enough for a research tool, not for a long-running service.
- **Runtime output is now confined to `server/logs/`** (server.out/err,
  shell.log, beacons.log, tv/). The toolkit directory stays clean, `logs/` is
  git-ignored, and the HTTP server refuses `/logs/**` with 404 so the directory
  is never served to the LAN. The page's `/save` dumps are pruned to the newest
  100 (`TV_OUTPUT_KEEP`), which fixes the earlier pile-up of `tv_output_*.txt`
  in `server/`.
- **Manual TV steps remain** (open the page, reboot) — by design; there is no
  paired remote-control channel.
- **License not chosen** — author decision. `NOTICE.md` covers third-party
  attribution only.
- **Task-list corruption under churn** (measured 2026-10-22): after many forks
  on a warm system, `init_task.tasks` was broken in **both** directions
  (`prev` at varying hops, `next` after one node). Neither the app payload nor
  the browser `kroot` path can find a task while that lasts; a reboot clears
  it. v6 avoids the self-inflicted orphans but does not repair a corrupted
  list.
- **pid-hash / IDR locator is BLOCKED (measured 2026-10-22).** The planned
  robust fix needs kernel symbols or a pid map, and this unit provides neither:
  - *Symbols:* the shipped `uImage` has **no kallsyms** (`vmlinux-to-elf` →
    `0 candidates for kallsyms_token_table`), `/proc/kallsyms` does not exist on
    the TV, and the GPL build (`research/sim/out/pontusml.System.map`) is a
    different kernel (`init_task` `0xC08F72C0` vs running `0xC0957180`) whose map
    omits the static `pid_hash`/`pidhash_shift`.
  - *IDR route:* `init_pid_ns` **was** located through `__ksymtab` —
    `0xC095CC70`, `level=0` — but the struct has **no `idr` field**: its fields
    end after `proc_work`/`pid_allocated`, and `struct pid_namespace.idr` only
    exists with `CONFIG_CHECKPOINT_RESTORE`, which this kernel does not enable.
  - *Remaining option:* a physical scan for the task comm (`~600 MB` low-memory
    range; slow and a bad pfn can fault). No list-independent locator is
    implemented.

## Validation performed

- `python -m py_compile` on all `tools/*.py` and `server/server.py`.
- `bash -n` on `server/deploy.sh` and `server/uninstall.sh`.
- Server smoke test on a non-privileged port: page/payload/scripts 200;
  traversal 404; `/server.py` and `/shell.log` 404.
- `root.ps1 -DryRun` and `uninstall.ps1 -DryRun`.
- Live end-to-end deploy test on the TV (see below).

## Live test (2026-10-22, TV on)

- `root.ps1 -Force -RestartServer`: fresh server, page load, stub paired;
  `kroot` initially failed on a corrupted task list (`no PHYSRPC1 task found`),
  which exposed the orphan-latch bug (finding #10).
- Cold reboot → v5 rooted at boot again (channel up at 70 s).
- Deployed **v6** over the channel: `SIZE=17920`, md5
  `d247e67a…`, `COPY=ok`, `DEPLOY_DONE`.
- Warm-restart test ×2 (`kill -9` the app): channel back in **11 s** and
  **8 s**, `uid=0` both times, `md5=d247e67a…`.
- Atomic deploy re-test through the channel: `COPY=ok`, `d247e67a…`.
- Deployed **v8** (18,944 B, `90406c6f…`): direct `real_parent` patch + spaced
  retries; proved that the comm/tail scans can fail on a warm system too.
- Deployed **v9** (19,456 B, `ffdb936f…`): fast-exit retry loop. Cold boot →
  root **38 s** (attempt 2); a boot with a badly damaged task list recovered in
  83 s (attempt 3), where v8 had needed 11 minutes. `deploy.sh` hash/size
  updated with it.
- Deployed **v7** (18,432 B, `20d60719…`, allowlist + video40 retry); verified
  the PC is allowed and the channel returns after a kill.
- **Uninstall test passed**: `uninstall.sh` restored the stock IL
  (`f61f60dd…`), the AOT (`6c9bdcc4…`), removed the boot row; after the reboot
  31337 stayed closed and `uninstall.ps1` exited 0.
- Re-rooting after uninstall exposed what *looked* like a boot-persistence
  regression. The hypothesis recorded here at the time — "the restored stock AOT
  was preferred" and "AUL did not start the app at boot" — was **wrong**; see the
  15:55 entry below. AUL launched the app on every boot, and the real cause was
  the payload DLL's SMACK label. Disabling the AOT in `deploy.sh` is still correct
  and unrelated. The task-list corruption also noted here (`prev` dies at hop
  5–17) is real, but it was never the reason the app did not start.
- State during that interval: **TV unrooted**, v7 on disk — resolved at 15:55.
- **Uninstall re-verified end-to-end (2026-10-22 16:56–17:03)** now that the
  label fix is in `uninstall.sh`: stock IL `f61f60dd…` and AOT `6c9bdcc4…`
  restored, both relabelled `User::Pkg::com.samsung.tv.MultiControl-Service::RO`
  (verified with `ls -lZ`), boot row removed, reload confirmed. After the
  reboot: **31337 stayed closed, no beacons**, and the **stock app was running**
  (`pid 2387`) with **no SMACK denial** in the audit log — so the undo path
  leaves a bootable, working stock app, which is exactly what the earlier test
  could not show.
- **New finding (2026-10-22 17:07):** after that stock restore, a root shell
  carrying the **browser** label cannot write the app's `bin/`
  (`touch`/`cp`/`rm` all `Permission denied`, `ls -ldZ bin` denied too), so
  `deploy.sh` failed on every write (`COPY=ok` was printed by the old logic that
  did not check the `cp` status — now fixed). Deployments that worked earlier
  (15:56, 16:33, 16:48, 16:53) all ran from the **app's own channel**, whose
  label matches the app directory. Consequence: the browser lane can *root* the
  TV but cannot install the payload into a stock app; the payload has to come
  from a context that carries the app label.
- Result: v6/v7 and uninstall are proven. **2026-10-22 15:55 — the "boot
  persistence needs the AUL fix" conclusion was wrong.** AUL did launch the app
  on every boot (4 SMACK denials in the kernel audit log); the process died
  before `Main` because the DLL carried the browser's SMACK label instead of the
  app's `::RO` label, so the .NET host was denied read on its own assembly.
  `deploy.sh` / `uninstall.sh` now set the label and verify it with `ls -lZ`
  (plain `ls` hides the label on this Tizen). Full write-up:
  `docs/BOOT-REGRESSION-SMACK-2026-10-22.md`.

## Recommendation

The PC/deploy path is solid enough to use as the production copy in this repo.
Before handing it to someone else: pick a license, decide the 31337 exposure,
and re-run the end-to-end flow on their TV/firmware (constants differ).
