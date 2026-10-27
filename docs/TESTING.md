# Testing this toolkit — on this TV and on yours

Several layers, from "runs anywhere" to "needs the TV". `python tools/test_all.py`
runs the offline ones and summarises (11 layers: the ones below plus the
public-release sanitizer selftest, the list-walk/DWARF fingerprint gate, and
the AGENTS.md state-row drift check); `--tv` adds the live-stub layer.

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
  label mismatch instead of printing `UNINSTALL_DONE`.

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
(blob is 7,720 B since the v40 stub pairing token):

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
   the md5 of `server/payload.dll` (v41: `1ab4343e…`, 33,792 B). The deploy gate
   is rendered from that file, so there is no constant in the scripts to compare.
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
