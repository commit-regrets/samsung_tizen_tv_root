"""Resolve a PID to its task_struct via init_pid_ns.idr (no task-list walk).

STATUS 2026-10-22: the __ksymtab lookup works — init_pid_ns resolves to
0xC095CC70 with level=0 — but this kernel's struct pid_namespace has **no idr
field** (it ends after proc_work/pid_allocated; the idr is only compiled with
CONFIG_CHECKPOINT_RESTORE, which is off). resolve() therefore cannot succeed.
Kept as the record of that route and as a base for a physical-scan fallback.

Route:
  1. find the "init_pid_ns" string in the kernel Image and the __ksymtab entry
     that points to it -> symbol VA,
  2. scan struct pid_namespace for the `idr` field,
  3. walk the radix tree for a pid number -> struct pid,
  4. follow pid.tasks[0] -> task_struct.pid_links[0].node,
  5. recover the task base by matching comm at +0x400.

Reads use the stub's READMANY op (64 pages per request), so the image scan is
seconds rather than minutes.

Usage: python find_pidns.py [pid]
"""
import struct
import sys

import physmap as T

IMAGE_BASE = 0x20008000
IMAGE_SIZE = 0x00B00000
STR = b"init_pid_ns\0"
O_TASK_COMM = 0x400
PAGE = 0x1000


def iter_pages(rpc, start, size, step=64):
    first = start & ~(PAGE - 1)
    pages = (start + size - first + PAGE - 1) // PAGE
    for i in range(0, pages, step):
        n = min(step, pages - i)
        for page, data in rpc.readmany(first + i * PAGE, n):
            if data is not None:
                yield page, data


def find_bytes(rpc, start, size, needle):
    tail = b""
    for page, data in iter_pages(rpc, start, size):
        buf = tail + data
        i = buf.find(needle)
        if i >= 0:
            return (page - len(tail) + i) & 0xFFFFFFFF
        tail = buf[-(len(needle) - 1):] if len(buf) >= len(needle) - 1 else buf
    return None


def find_symbol(rpc, name):
    needle = name.encode() + b"\0"
    # ksymtab strings live near the end of .rodata; try that window first
    windows = [(0x780000, 0x280000), (0, IMAGE_SIZE)]
    found = None
    for start, size in windows:
        found = find_bytes(rpc, IMAGE_BASE + start, size, needle)
        if found is not None:
            break
    if found is None:
        print(f"[-] string {name!r} not found", flush=True)
        return None
    str_va = (found + 0xA0000000) & 0xFFFFFFFF
    print(f"[+] {name} string at {T.hexs(found)} va {T.hexs(str_va)}", flush=True)

    pat = struct.pack("<I", str_va)
    entry = find_bytes(rpc, IMAGE_BASE, IMAGE_SIZE, pat)
    if entry is None:
        print("[-] no pointer to the string", flush=True)
        return None
    # entry points at the name field; value is the u32 before it
    value = rpc.read_u32((entry - 4) & 0xFFFFFFFF)
    ns = rpc.read_u32((entry + 4) & 0xFFFFFFFF)
    print(f"[*] entry {T.hexs(entry)} value={T.hexs(value)} ns={ns}", flush=True)
    if not T._kernel_ptr(value) or ns != 0:
        print("[-] entry does not look like a kernel_symbol", flush=True)
        return None
    return value


def ru32(rpc, va):
    return rpc.read_u32((va - 0xA0000000) & 0xFFFFFFFF)


def ru8(rpc, va):
    return rpc.read((va - 0xA0000000) & 0xFFFFFFFF, 1)[0]


def resolve(rpc, ns_va, pid):
    for c in range(0, 0x140, 4):
        try:
            gfp = ru32(rpc, ns_va + c)
            root = ru32(rpc, ns_va + c + 4)
        except Exception:
            continue
        if not T._kernel_ptr(root) or gfp > 0xFFFF:
            continue
        node = root
        if node & 2:
            node &= ~3
            shift = None
            for shift_off in (0, 0x118, 0x08):
                try:
                    s = ru8(rpc, node + shift_off)
                except Exception:
                    continue
                if 0 < s < 16:
                    shift = s
                    break
            if shift is None:
                continue
            if pid >> shift:
                continue                    # deeper tree: not handled yet
            idx = pid & 63
            slot = None
            for slots_off in (0x14, 0x08):
                try:
                    v = ru32(rpc, node + slots_off + 4 * idx)
                except Exception:
                    continue
                if T._kernel_ptr(v) and not (v & 2):
                    slot = v
                    break
            if slot is None:
                continue
        else:
            if pid != 0:
                continue
            slot = root
        pid_va = slot
        try:
            level = ru32(rpc, pid_va + 4)
            nr = ru32(rpc, pid_va + 0x2C)
            first = ru32(rpc, pid_va + 0x0C)
        except Exception:
            continue
        if level > 2 or nr != pid or not T._kernel_ptr(first):
            continue
        for o in range(0, 0x600, 4):
            base = (first - o) & 0xFFFFFFFF
            try:
                comm = rpc.read((base - 0xA0000000) & 0xFFFFFFFF, 16)
            except Exception:
                continue
            name = comm.split(b"\0")[0]
            if name and all(32 <= ch < 127 for ch in name):
                print(f"[+] idr_off={c:#x} pid_links_off={o:#x} "
                      f"pid={T.hexs(pid_va)} task={T.hexs(base)} "
                      f"comm={name.decode()!r}", flush=True)
                return True
    return False


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    rpc = T.RPC(timeout=20)
    try:
        ns_va = find_symbol(rpc, "init_pid_ns")
        if ns_va is None:
            return 1
        try:
            level = ru32(rpc, ns_va + 4)
            print(f"[*] init_pid_ns level={level}", flush=True)
        except Exception as exc:
            print(f"[-] cannot read init_pid_ns: {exc}", flush=True)
            return 1
        if not resolve(rpc, ns_va, pid):
            print(f"[-] no idr candidate resolved pid {pid}", flush=True)
            return 1
        return 0
    finally:
        rpc.close()


if __name__ == "__main__":
    raise SystemExit(main())
