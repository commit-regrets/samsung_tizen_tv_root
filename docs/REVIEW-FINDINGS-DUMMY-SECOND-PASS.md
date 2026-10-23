# Dummy findings file — second-pass only (TEMPORARY)

> Not a replacement for `REVIEW-FINDINGS-2026-10-23.md`. This is the isolated
> second-pass set, written so it can be checked on its own against the
> `research/sim` DWARF kernel and the Fake-RPC / page-scan harness. Do not
> commit. Delete with the parent findings file.

Checked against `samsungtv/research/sim/out/pontusml.vmlinux` DWARF on
2026-10-23 (`task_struct` + `cred` early-exit dump). QEMU boot of this
kernel still has no serial console (`research/sim/out/console.log`), so
layout claims use DWARF, not a running VM.

## Layout the dummy assumes (sim DWARF, matched TV for these fields)

| Field | Sim offset | TV / payload |
|---|---|---|
| `task_struct.tasks` | +0x23C | payload `offs` / AGENTS.md |
| `task_struct.real_parent` | +0x2F0 | `Program.cs` parentOffs |
| `task_struct.real_cred` | +0x3F4 | `O_REAL` |
| `task_struct.cred` | +0x3F8 | `O_CRED` |
| `task_struct.comm` | +0x400 | `O_COMM` |
| `cred.usage` | +0x00 | Python `_sane_cred`; C# never reads it |
| `cred.uid` | +0x04 | `CredUid` |
| `cred.cap_inheritable` | +0x28 (40) | Python `patch_full` misreads this as uid |
| `cred.cap_permitted` | +0x30 (48) | C# `PatchCred` / Python `O_CAP_PERMITTED` |
| `cred.cap_effective` | +0x38 (56) | C# / `O_CAP_EFFECTIVE` |

## Dummy findings

### Finding 14 correction (current file half-wrong)
`mmap64` `== (IntPtr)(-1)` is the correct libc `MAP_FAILED` check. Do not
treat `-4095..-1` as mmap64 errors. The `mmap2` fallback `if (r < 0)` is
too strict: a successful mapping in the high half of VA is a negative
`int32`. The `Pages.Clear()` leak without `munmap` is still real.

### M1. Fast-exit children hold `/dev/video40`
`fork()` child (`Program.cs` ~524–528) sleeps 120 s and never `close(_fd)`.
`Environment.Exit(0)` on the fast-exit path (~668) does not reap it. Next
AUL launch then waits on the 120 s open-retry. Close the fd in the child
and before `Exit`.

### M2. POST `/save` Content-Length uncapped
`server.py:_read_full_request` caps headers, then reads `clen` with no max.

### M3. Stub `op_read`/`op_write` do not clamp to the mapped page
`physrpc.S`: `add r1, r9, r10` then `send_full`/`str` using `r11` as
length/value. No compare against 0x1000.

### M4. C# `PatchCred` has no `_sane_cred`
Sim `cred.usage` is +0. Python `_sane_cred` rejects `usage > 0x10000` and
wild ids. C# only checks `CredUid` is 0 or 5001, then writes. A bogus
kernel-looking pointer to a uid-0 cred (including `init`) would be patched.

### M5. Cred-content scan misses a 32-byte pattern that straddles a page
`scan_cred.py` / `tv_rootwatch.root_by_cred_scan` `data.find(PAT)` per 4 K
page, no overlap window.
