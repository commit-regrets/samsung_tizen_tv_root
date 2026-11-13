#!/usr/bin/env python3
"""Layout-shift-proof task-list location and walk (read-only diagnostic).

The measured offsets (task list at task+0x23c, linked through prev) are valid
only for this firmware.  On another model they must be re-measured - or
sidestepped: a doubly-linked list_head carries its own validation in its
circular back-links (next.prev == &head and prev.next == &head), so any
plausible list_head near init_task can be *proven* to be a list before walking
it, and the walk can find a comm tag without ever knowing the task-list
offset.  That is the whole porting story for a second model: run this, and the
offsets it discovers can then be cross-checked against the DWARF reader
(`tools/dwarf_offsets.py`).

    python tools/listwalk.py               # offline self-test (sim memory)
    python tools/test_listwalk.py          # the same test, wired into test_all

RPC-agnostic: every function takes an object with `read(phys, n)` and
`read_u32(phys)` - `physmap.RPC` against a live stub, or `sim_rpc.MemRPC` in
tests.  Read-only: nothing here writes.

Ported from the research tree (recon/tvphys.py list_candidates /
find_self_via_lists, 2026-10-26).
"""
import struct

PHYS_OFF = 0xA0000000          # v = phys + PHYS_OFF (VMSPLIT_3G, PHYS_OFFSET 0x20000000)
SCAN_BYTES = 0x400             # init_task region to probe for list_heads
MAX_ENTRIES = 2500


def _kernel_ptr(v: int) -> bool:
    """Pointer shape only (trap 5): accept the full 32-bit direct map."""
    return 0xC0000000 <= v < 0x100000000


def v2p(v: int) -> int:
    return (v - PHYS_OFF) & 0xFFFFFFFF


def p2v(p: int) -> int:
    return (p + PHYS_OFF) & 0xFFFFFFFF


def list_candidates(rpc, init_phys: int):
    """Offsets of list_heads inside init_task's first SCAN_BYTES bytes whose
    circular back-links validate (next.prev and prev.next both point home).
    Absolute virtual addresses only; no struct-offset assumption."""
    init_virt = p2v(init_phys)
    page = rpc.read(init_phys, SCAN_BYTES)
    cands = []
    for o in range(0, SCAN_BYTES - 8, 4):
        nxt, prv = struct.unpack_from("<II", page, o)
        if not (_kernel_ptr(nxt) and _kernel_ptr(prv)):
            continue
        head = (init_virt + o) & 0xFFFFFFFF
        if nxt == head and prv == head:
            cands.append(o)            # empty list: trivially self-consistent
            continue
        if nxt == head or prv == head:
            continue
        try:
            if rpc.read_u32(v2p(prv)) != head:
                continue
            if rpc.read_u32(v2p(nxt) + 4) != head:
                continue
        except OSError:
            continue
        cands.append(o)
    return cands


def walk_list(rpc, init_phys: int, tasks_off: int, tag: bytes,
              max_entries: int = MAX_ENTRIES):
    """Walk the list at init_task+tasks_off; return (entry_virt, task_virt,
    tag_phys, hops) of the first entry whose page holds `tag`, or None.

    The tag is searched in a 0x1000 window at the translated entry's page so a
    task_struct that starts anywhere in the page is still found (tasks are NOT
    page-aligned - 0xe2df7300 was seen at page offset 0x300)."""
    init_virt = p2v(init_phys)
    head = (init_virt + tasks_off) & 0xFFFFFFFF
    try:
        nxt = rpc.read_u32(v2p(head))
    except OSError:
        return None
    seen = set()
    for hops in range(max_entries):
        if nxt == head or nxt == 0 or nxt in seen:
            return None
        seen.add(nxt)
        page_phys = v2p(nxt) & ~0xFFF
        try:
            window = rpc.read(page_phys, 0x1000)
        except OSError:
            return None
        pos = window.find(tag)
        if pos >= 0:
            entry_task = (nxt - tasks_off) & 0xFFFFFFFF
            return nxt, entry_task, page_phys + pos, hops
        try:
            nxt = rpc.read_u32(v2p(nxt))
        except OSError:
            return None
    return None


def find_tag_via_lists(rpc, init_phys: int, tag: bytes):
    """Validate every list_head near init_task, walk each, return the first
    (list_off, entry_virt, task_virt, tag_phys, hops) that finds `tag`."""
    for off in list_candidates(rpc, init_phys):
        hit = walk_list(rpc, init_phys, off, tag)
        if hit is not None:
            return (off,) + hit
    return None


# ---- offline self-test (no TV): plant a task list in sim memory -------------

def _selftest() -> int:
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from sim_rpc import MemRPC

    phys_off_v = PHYS_OFF
    init_phys = 0x20957180
    init_virt = p2v(init_phys)
    tag = b"PHYRFORK\0"

    def plant(mem, phys: int, off: int, data: bytes):
        # `phys` need not be page-aligned (init_task is at 0x...7180): the
        # struct offset counts from the struct, the page buffer from its base.
        base = phys & ~0xFFF
        o = (phys & 0xFFF) + off
        mem._page(base)[o:o + len(data)] = data

    ok = True

    def check(name, cond, note=""):
        nonlocal ok
        print(("PASS" if cond else "FAIL"), name, ("- " + note if note else ""))
        ok = ok and cond

    # Case 1: a valid two-entry list through tasks_off=0x23c, plus decoys.
    rpc = MemRPC()
    tasks_off = 0x23C
    t1_phys, t2_phys = 0x21000000, 0x22000300   # second task NOT page-aligned
    t1_virt, t2_virt = p2v(t1_phys), p2v(t2_phys)
    head_v = init_virt + tasks_off
    # head.next = first element (t2), head.prev = last element (t1): the ring
    # must close through BOTH ends or the back-link check rightly refuses it.
    plant(rpc, init_phys, tasks_off,
          struct.pack("<II", t2_virt + tasks_off, t1_virt + tasks_off))
    plant(rpc, t2_phys, tasks_off,
          struct.pack("<II", t1_virt + tasks_off, head_v))
    plant(rpc, t1_phys, tasks_off,
          struct.pack("<II", head_v, t2_virt + tasks_off))
    plant(rpc, t2_phys, 0x400, tag)
    # decoy: a kernel-pointer pair that is NOT back-linked
    plant(rpc, init_phys, 0x300, struct.pack("<II", t1_virt, t2_virt))

    cands = list_candidates(rpc, init_phys)
    check("validates only the real list (+empty-head decoys)", tasks_off in cands
          and 0x300 not in cands, f"cands={[hex(c) for c in cands]}")
    hit = walk_list(rpc, init_phys, tasks_off, tag)
    check("walks to the tag", hit is not None and hit[2] == t2_phys + 0x400,
          f"hit={hit}")
    check("entry -> task subtraction is exact",
          hit is not None and hit[1] == t2_virt)

    # Case 2: empty lists validate as candidates; the walk simply finds nothing.
    rpc2 = MemRPC()
    plant(rpc2, init_phys, 0x100, struct.pack("<II", init_virt + 0x100,
                                              init_virt + 0x100))
    cands2 = list_candidates(rpc2, init_phys)
    check("an empty list validates", 0x100 in cands2, f"cands={cands2}")
    check("walk on an empty list finds nothing",
          walk_list(rpc2, init_phys, 0x100, tag) is None)
    check("no tag anywhere -> find_tag_via_lists returns None",
          find_tag_via_lists(rpc2, init_phys, tag) is None)

    # Case 3: a broken back-link disqualifies the head.
    rpc3 = MemRPC()
    plant(rpc3, init_phys, 0x180, struct.pack("<II", t1_virt, t2_virt))
    plant(rpc3, t1_phys, 0, struct.pack("<I", 0xDEAD))
    check("broken back-link is rejected", 0x180 not in list_candidates(rpc3, init_phys))

    print("\nlistwalk selftest:", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
