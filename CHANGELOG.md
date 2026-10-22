# Changelog

All notable changes to this toolkit, newest first. Dates are day-level and times
are deliberately omitted — the *why* of a change belongs here, the *how* belongs
in `docs/`.

**Maintenance rule:** every change to the scripts, payload, server or docs gets an
entry here, under `Unreleased` if it is not part of a dated batch. A change with no
entry is an incomplete change. `AGENTS.md` repeats this rule for agents.

---

## Unreleased

### Added

- `CHANGELOG.md` (this file), plus a rule in `AGENTS.md`: any future change must be
  recorded here with its reasoning. The dated narrative that had accumulated in
  `AGENTS.md` and the docs now lives here; those files describe the current state and
  the how, not the history.

### Changed

- `AGENTS.md` gained a "Maintaining this repo" section defining that split, and the
  narrative history paragraph became a pointer to this file.
- `README.md` documentation index lists the changelog.

---

## 2026-10-22

The day the mechanism was proven, broken, and proven again — and the repo was made
readable.

### Added

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
