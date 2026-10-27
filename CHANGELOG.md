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

