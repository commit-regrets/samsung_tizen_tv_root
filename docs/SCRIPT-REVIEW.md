# Script review — production readiness

Audit of the toolkit in this repo. Scope: `root.ps1`, `uninstall.ps1`,
`server/server.py`, `server/deploy.sh`, `server/uninstall.sh`, and `tools/*.py`.

**State: validated end to end from a stock TV.** `uninstall.ps1` → reboot (the
channel stayed closed) → `root.ps1` → reboot → channel up in **47 s**, `uid=0`, no
PC and no browser. The sequence of changes behind that is in `CHANGELOG.md`; this
document is about the scripts as they are now.

## Fixed

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | **high** | `auto_root.py` returned success even when the deploy script failed — `run()`'s output was discarded, so `root.ps1` printed "Deploy verified" after a failed `cp`. | It requires `DEPLOY_DONE` and `COPY=ok` in the output (`--expect`) and exits non-zero otherwise. |
| 2 | **high** | `root.ps1 -RestartServer` only restarted when the server was *not* ours; reusing our own server kept stale RPC waiters that stole the next stub. | `-RestartServer` always stops and starts the server. |
| 3 | medium | `Stop-ToolkitServer` killed any process whose command line contained `server.py`. | It also requires the process name to be `python`/`pysrv`. |
| 4 | medium | A stale `/tmp/keep_boot` marker could silently keep the boot row during uninstall. | `uninstall.ps1` removes the marker unless `-KeepBoot`. |
| 5 | medium | `server.py` appended to `shell.log` without bound (it reached 58 MB). | Rotates to `shell.log.1` at 8 MB. |
| 6 | medium | The HTTP server would serve its own source and logs to anyone on the LAN. | Deny list for `.py .log .out .err .db .pem .key .journal` and the known log names → 404. |
| 7 | low | A slow HTTP client could block the single-threaded accept loop indefinitely. | 10 s socket timeout for HTTP handling. |
| 8 | low | `uninstall.sh` picked an arbitrary `.native_image.disabled.*` directory when several existed. | `ls -dt` (newest first). |
| 9 | low | No attribution or requirements files. | `NOTICE.md`, `tools/requirements.txt` (rebuild only). |
| 10 | **high** | The boot payload latched onto a stale `PHYRFORK` orphan from an earlier AUL restart, patching the wrong cred on warm restarts. | v6+: snapshot existing landmarks, wait for a *new* child, validate the cred before patching, keep the landmark 120 s. |
| 11 | medium | `deploy.sh` / `uninstall.sh` copied straight onto the live DLL; a kill mid-copy left a truncated file. | Copy to `*.tmp` in the same directory, then `mv` (atomic rename). |
| 12 | medium | `physmap.readmany()` desynchronised whenever the stub hit an unmappable page — every later read returned garbage, so a scan looked like a clean negative. | The client stops at the bad page and restarts after it; verified `readmany` == direct read on the same page. |
| 13 | **high** | Deploying from the browser-labelled stub always failed (`COPY=fail`), because that label cannot write the app's `bin/`. `root.ps1` inherited the bug. | `root.ps1` injects a relabel prelude into the generated script; `server/recover.sh` does the same by hand. |
| 14 | medium | `aulctl stop` blocks while the payload is running, so the deploy hung before `DEPLOY_DONE`. | The stop+start runs detached; the script always returns. |
| 15 | medium | `deploy.sh` / `uninstall.sh` trusted their SQL — a `DELETE`/`INSERT` that matched nothing looked like success. | Both read `boot_sequence` back (`BOOT_ROW_COUNT=1`, `remain=0`) and fail loudly. |
| 16 | medium | `RSET` evicted a client that was merely *waiting* for a stub, so a stub connecting between two attempts was destroyed. | The server only evicts a client that is actually paired; the client no longer resets while waiting. |

## Race conditions — status

| Race | Status |
|---|---|
| Parent scans before the child sets its comm, then patches a stale orphan | **Fixed** (v6 pre-fork snapshot + wait for a *new* child). |
| `kernel_root.py` picks the first `PHYRFORK` | **Fixed** with the same exclusion set; still limited by the task list. |
| Half-written DLL if the app dies during the copy | **Fixed** (temp + atomic rename). |
| Stale RPC waiter consuming the next stub | **Fixed**: waiting clients are no longer evicted, and `physmap.reset_stub()` clears a wedged pairing without a restart. |
| Slow HTTP client blocking the accept loop | **Mitigated**: 10 s timeout; still single-threaded. |
| Task list corrupted while walking it | **Open**, but no longer on the critical path: root uses the cred-pattern scan, and the task locator uses `init.tasks.prev` immediately after a fork. |
| `/dev/video40` opener conflict (browser vs payload) | **Open by design**: one RDWR opener. The payload closes the device after rooting; a page reload while a stale renderer holds it needs that renderer gone (see `docs/USAGE.md`). |

## Known limitations (accepted / documented)

- **No authentication on the RPC gateway**; it binds `127.0.0.1` only. The TV root
  channel binds `0.0.0.0:31337`, which is a LAN-wide root service. The payload
  supports an allowlist (`shared/rootchan.allow`, one IP per line, written by
  `deploy.sh`); treat the exposure as a decision to make, not a default to accept.
- **Single-threaded HTTP accept loop.** Fine for one TV.
- **Hardcoded firmware constants** (`init_task`, offsets, Image base) in the
  payload and tools. Re-measure on another model — see `docs/PORTABILITY.md`.
- **Hardcoded hashes**: `deploy.sh` pins the payload md5 and size, so it refuses to
  install a different build; `uninstall.sh` pins the *stock* IL/AOT md5s and refuses
  to restore anything else. Both are deliberate. Update the deploy constants when
  the payload changes.
- **Log rotation keeps one generation**; enough for a research tool, not a service.
- **Runtime output is confined to `server/logs/`** and `/logs/**` is 404, so logs
  are never served.
- **Manual TV steps remain** (open the page, reboot) — there is no paired
  remote-control channel to automate them.
- **License not chosen** — author decision; `NOTICE.md` covers attribution only.
- **pid-hash / IDR locator is still blocked** (the shipped kernel has no kallsyms,
  and `init_pid_ns` has no `idr` field without `CONFIG_CHECKPOINT_RESTORE`). It no
  longer matters: the cred-pattern scan replaced it.
- **Two tools in `tools/` cannot run from this repo as-is.** `find_task.py` imports
  `smack_borrow`, which lives only in the reference tree, and `smack_relabel.py`
  belongs to the same dead-end kernel-relabel path (`docs/FAILED.md`). Treat both
  as reference-only, or port `smack_borrow` in before using them.
  `dwarf_offsets.py` also lives only in the reference tree (`recon/`), although
  `docs/PORTABILITY.md` recommends it for re-measuring offsets on another model —
  port it with a `--vmlinux` argument if that work starts.

## Validation performed

- `python -m py_compile` on every `tools/*.py` and `server/server.py`; `sh -n` on
  the shell scripts, including the generated `deploy_local.sh`.
- Server smoke tests on a non-privileged port: page/scripts 200, traversal 404,
  `/server.py` and `/shell.log` 404.
- `root.ps1 -DryRun`, `uninstall.ps1 -DryRun`.
- Live deploy over the root channel and over the browser stub, at payload versions
  v5 through v13 (all with hash and size gated by `deploy.sh`).
- Cold boots measured between **38 s and 47 s** to root, with no PC involvement.
- Warm restart: `kill -9` of the app re-roots on AUL's next relaunch.
- Uninstall end to end: stock IL/AOT restored and relabelled, boot row verified
  gone, channel stayed closed after the reboot, stock app running with no SMACK
  denial.
- One-click end to end from stock (uninstall → reboot → `root.ps1` → reboot).

## Recommendation

The PC and deploy paths are solid enough to use as the production copy, and the
one-click flow has been exercised from a stock TV. Before handing it to someone
else: pick a license, decide the 31337 exposure (use the allowlist), and re-run the
flow on their TV and firmware — the constants differ.
